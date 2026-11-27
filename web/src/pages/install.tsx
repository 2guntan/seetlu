import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  ApiError,
  get,
  patch,
  post,
  put,
  type CameraIn,
  type ClipRequest,
  type CameraSetup,
  type CountCheck,
  type Kit,
  type KitSetup,
  type Shop,
  type Zone,
  type ZoneType,
} from "../api/client";
import { CameraChecks } from "../components/camera-checks";
import { ZoneEditor } from "../components/zone-editor";
import { ErrorMessage } from "../components/states";
import { useAuth } from "../lib/use-auth";
import { useCommandClip } from "../lib/use-command";
import { normalizePhone, parseQr } from "../lib/parse";

type Step = 1 | 2 | 3 | 4 | 5;
const CATEGORIES = ["boutique", "superette", "pharmacie", "quincaillerie", "salon", "telephonie", "other"];
const DEFAULT_HOURS = Object.fromEntries(
  ["mon", "tue", "wed", "thu", "fri", "sat"].map((d) => [d, [["08:00", "21:00"]]]).concat([["sun", []]]),
);

interface BarcodeDetectorLike {
  detect(src: HTMLVideoElement): Promise<{ rawValue: string }[]>;
}

function QrScanner({ onCode }: { onCode: (text: string) => void }) {
  const { t } = useTranslation();
  const [on, setOn] = useState(false);
  const Detector = (window as unknown as { BarcodeDetector?: new (o: object) => BarcodeDetectorLike }).BarcodeDetector;
  useEffect(() => {
    if (!on || !Detector) return;
    let stream: MediaStream | undefined;
    let stop = false;
    const video = document.getElementById("qr-video") as HTMLVideoElement | null;
    const det = new Detector({ formats: ["qr_code"] });
    void navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(async (s) => {
      stream = s;
      if (!video) return;
      video.srcObject = s;
      await video.play();
      while (!stop) {
        const codes = await det.detect(video).catch(() => []);
        if (codes[0]) {
          onCode(codes[0].rawValue);
          break;
        }
        await new Promise((r) => setTimeout(r, 300));
      }
    });
    return () => {
      stop = true;
      stream?.getTracks().forEach((tr) => tr.stop());
    };
  }, [on, Detector, onCode]);
  if (!Detector) return <p className="muted">{t("install.scanUnsupported")}</p>;
  return on ? (
    <video id="qr-video" muted playsInline />
  ) : (
    <button type="button" onClick={() => setOn(true)}>
      {t("install.scan")}
    </button>
  );
}

function ClaimStep({ onDone }: { onDone: (serial: string, token: string) => void }) {
  const { t } = useTranslation();
  const [serial, setSerial] = useState("");
  const [token, setToken] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onDone(serial.trim(), token.trim());
  };
  return (
    <form className="card" onSubmit={submit}>
      <h2>{t("install.claim")}</h2>
      <QrScanner
        onCode={(text) => {
          const p = parseQr(text);
          if (p) onDone(p.serial, p.claim_token);
        }}
      />
      <label>
        {t("install.serial")}
        <input name="serial" value={serial} onChange={(e) => setSerial(e.target.value)} required />
      </label>
      <label>
        {t("install.claimToken")}
        <input name="claim_token" value={token} onChange={(e) => setToken(e.target.value)} required />
      </label>
      <button type="submit">{t("install.next")}</button>
    </form>
  );
}

function ShopStep({ serial, token, onDone }: { serial: string; token: string; onDone: (kit: Kit, shop: Shop) => void }) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const [shopId, setShopId] = useState("");
  const [f, setF] = useState({ name: "", address: "", category: "boutique", cdp: "", ownerName: "", ownerPhone: "", lat: "", lng: "" });
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  const go = useMutation({
    mutationFn: async () => {
      let shop: Shop;
      if (shopId) {
        shop = await patch<Shop>(`/v1/shops/${shopId}`, f.cdp ? { cdp_declaration_ref: f.cdp } : {});
      } else {
        shop = await post<Shop>("/v1/shops", {
          name: f.name,
          category: f.category,
          address: f.address || null,
          gps_lat: f.lat ? Number(f.lat) : null,
          gps_lng: f.lng ? Number(f.lng) : null,
          opening_hours: DEFAULT_HOURS,
          cdp_declaration_ref: f.cdp || null,
          owner: { name: f.ownerName, phone_e164: normalizePhone(f.ownerPhone) },
        });
      }
      const kit = await post<Kit>("/v1/kits/claim", { serial, claim_token: token, shop_id: shop.id });
      return { kit, shop };
    },
    onSuccess: ({ kit, shop }) => {
      void qc.invalidateQueries({ queryKey: ["me"] });
      onDone(kit, shop);
    },
  });
  const gps = () =>
    navigator.geolocation?.getCurrentPosition((p) => {
      set("lat", p.coords.latitude.toFixed(6));
      set("lng", p.coords.longitude.toFixed(6));
    });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    go.mutate();
  };
  return (
    <form className="card" onSubmit={submit}>
      <h2>{t("install.shop")}</h2>
      <label>
        {t("install.pickShop")}
        <select name="shop" value={shopId} onChange={(e) => setShopId(e.target.value)}>
          <option value="">{t("install.newShop")}</option>
          {me?.shops.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      {!shopId && (
        <>
          <label>
            {t("settings.name")}
            <input name="shop_name" value={f.name} onChange={(e) => set("name", e.target.value)} required />
          </label>
          <label>
            {t("install.category")}
            <select value={f.category} onChange={(e) => set("category", e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            {t("install.address")}
            <input name="address" value={f.address} onChange={(e) => set("address", e.target.value)} />
          </label>
          <div className="row">
            <span>
              {t("install.gps")}: {f.lat && f.lng ? `${f.lat}, ${f.lng}` : t("common.none")}
            </span>
            <button type="button" className="ghost" onClick={gps}>
              {t("install.useGps")}
            </button>
          </div>
          <label>
            {t("install.ownerName")}
            <input name="owner_name" value={f.ownerName} onChange={(e) => set("ownerName", e.target.value)} required />
          </label>
          <label>
            {t("install.ownerPhone")}
            <input name="owner_phone" type="tel" value={f.ownerPhone} onChange={(e) => set("ownerPhone", e.target.value)} required />
          </label>
        </>
      )}
      <label>
        {t("settings.cdp")}
        <input name="cdp" value={f.cdp} onChange={(e) => set("cdp", e.target.value)} />
      </label>
      <button type="submit" disabled={go.isPending}>
        {t("install.next")}
      </button>
      <ErrorMessage error={go.error} />
    </form>
  );
}

function CameraZones({
  shopId,
  kitId,
  cam,
  setup,
  onChange,
}: {
  shopId: string;
  kitId: string;
  cam: CameraIn;
  setup: CameraSetup | undefined;
  onChange: (c: CameraIn) => void;
}) {
  const { t } = useTranslation();
  const [commandId, setCommandId] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<ZoneType | null>(null);
  const { clip } = useCommandClip(commandId);
  const snap = useMutation({
    mutationFn: () => post<ClipRequest>(`/v1/shops/${shopId}/snapshot`, undefined, { camera: cam.name }),
    onSuccess: (r) => setCommandId(r.command_id ?? null),
  });
  const kinds: ZoneType[] = cam.role === "door" ? ["door_line"] : ["customer_side", "staff_side"];
  const addPoint = (p: [number, number]) => {
    if (!drawing) return;
    const zones = [...cam.zones];
    let z = zones.find((x) => x.type === drawing);
    if (!z) {
      z = { type: drawing, geometry: [], inward_side: drawing === "door_line" ? "left" : null };
      zones.push(z);
    }
    if (drawing === "door_line" && z.geometry.length >= 2) z.geometry = [];
    z.geometry = [...z.geometry, p];
    onChange({ ...cam, zones: zones.map((x) => (x.type === drawing ? (z as Zone) : x)) });
  };
  const door = cam.zones.find((z) => z.type === "door_line");
  return (
    <section className="card" data-testid={`camera-${cam.name}`}>
      <h2>{t(`install.role.${cam.role}`)}</h2>
      {setup ? <CameraChecks key={setup.stream?.source ?? "none"} kitId={kitId} cam={setup} /> : null}
      <button type="button" className="ghost" onClick={() => snap.mutate()} disabled={snap.isPending || (!!commandId && !clip)}>
        {commandId && !clip ? t("install.snapshotWait") : t("install.snapshot")}
      </button>
      <ZoneEditor imageUrl={clip?.url ?? null} zones={cam.zones} drawing={drawing} onPoint={addPoint} />
      <div className="row mt">
        {kinds.map((k) => (
          <button key={k} type="button" className={drawing === k ? "" : "ghost"} onClick={() => setDrawing(k)}>
            {k === "door_line" ? t("install.drawDoor") : k === "customer_side" ? t("install.drawCustomer") : t("install.drawStaff")}
          </button>
        ))}
        <button type="button" className="ghost" onClick={() => onChange({ ...cam, zones: [] })}>
          {t("install.clear")}
        </button>
      </div>
      {door && (
        <label className="inline">
          {t("install.inside")}
          <select
            value={door.inward_side ?? "left"}
            onChange={(e) =>
              onChange({ ...cam, zones: cam.zones.map((z) => (z === door ? { ...z, inward_side: e.target.value as "left" | "right" } : z)) })
            }
          >
            <option value="left">{t("install.left")}</option>
            <option value="right">{t("install.right")}</option>
          </select>
        </label>
      )}
    </section>
  );
}

function ZonesStep({ kit, shop, onDone }: { kit: Kit; shop: Shop; onDone: () => void }) {
  const { t } = useTranslation();
  const [cams, setCams] = useState<CameraIn[]>([
    { name: "door", role: "door", zones: [] },
    { name: "counter", role: "counter", zones: [] },
  ]);
  const save = useMutation({ mutationFn: () => put(`/v1/kits/${kit.id}/cameras`, cams), onSuccess: onDone });
  // AC-F8-6..8: the box reports each slot's stream once the installer picks the channel on its LAN page
  const setup = useQuery({
    queryKey: ["kit-setup", kit.id],
    queryFn: () => get<KitSetup>(`/v1/kits/${kit.id}/setup`),
    refetchInterval: 5000,
  });
  return (
    <div>
      <h2>{t("install.cameras")}</h2>
      <p className="muted">{t("install.recorderHelp", { serial: kit.serial })}</p>
      {cams.map((c, i) => (
        <CameraZones
          key={c.name}
          shopId={shop.id}
          kitId={kit.id}
          cam={c}
          setup={setup.data?.cameras.find((s) => s.role === c.role)}
          onChange={(nc) => setCams(cams.map((x, j) => (j === i ? nc : x)))}
        />
      ))}
      <button onClick={() => save.mutate()} disabled={save.isPending}>
        {t("install.saveZones")}
      </button>
      <ErrorMessage error={save.error} />
    </div>
  );
}

function CountStep({ kit, onDone }: { kit: Kit; onDone: () => void }) {
  const { t } = useTranslation();
  const [check, setCheck] = useState<CountCheck | null>(null);
  const [n, setN] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<CountCheck | null>(null);
  useEffect(() => {
    if (!check || result) return;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - Date.parse(check.started_at)) / 1000)), 1000);
    return () => clearInterval(id);
  }, [check, result]);
  const start = useMutation({
    mutationFn: () => post<CountCheck>(`/v1/kits/${kit.id}/count-checks`),
    onSuccess: (c) => {
      setCheck(c);
      setN(0);
      setResult(null);
    },
  });
  const stop = useMutation({
    mutationFn: (withReason: boolean) =>
      post<CountCheck>(`/v1/count-checks/${check?.id}/stop`, {
        manual_count: n,
        override_reason: withReason ? reason : null,
      }),
    onSuccess: setResult,
  });
  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  return (
    <section className="card">
      <h2>{t("install.countCheck")}</h2>
      <p className="muted">{t("install.countHelp")}</p>
      {!check && <button onClick={() => start.mutate()}>{t("install.start")}</button>}
      {check && !result && (
        <>
          <p>
            <b>{mmss}</b> · <span data-testid="manual-count">{t("install.manual", { n })}</span>
          </p>
          <button className="big" onClick={() => setN(n + 1)} data-testid="plus-one">
            {t("install.plusOne")}
          </button>
          <p>
            <button onClick={() => stop.mutate(false)}>{t("install.stop")}</button>
          </p>
        </>
      )}
      {result && (
        <div data-testid="count-result">
          <p>{t("install.manual", { n: result.manual_count })}</p>
          <p>{t("install.agent", { n: result.agent_count })}</p>
          {result.error_pct !== null && <p>{t("install.error", { pct: result.error_pct })}</p>}
          <p>
            <b>{result.passed ? t("install.passed") : t("install.failed")}</b>
          </p>
          {result.passed || result.override_reason ? (
            <button onClick={onDone}>{t("install.next")}</button>
          ) : (
            <>
              <button className="ghost" onClick={() => start.mutate()}>
                {t("install.start")}
              </button>
              <label>
                {t("install.override")}
                <input name="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button disabled={reason.trim().length < 5 || stop.isPending} onClick={() => stop.mutate(true)}>
                {t("install.override")}
              </button>
            </>
          )}
        </div>
      )}
      <ErrorMessage error={start.error ?? stop.error} />
    </section>
  );
}

function ActivateStep({ kit }: { kit: Kit }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: () => post<Kit>(`/v1/kits/${kit.id}/activate`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
  const err = act.error instanceof ApiError ? act.error : null;
  return (
    <section className="card">
      <button onClick={() => act.mutate()} disabled={act.isPending || act.isSuccess}>
        {t("install.activate")}
      </button>
      {act.isSuccess && <p role="status">{t("install.activated")}</p>}
      {err?.type.endsWith("cdp-missing") && <p className="error">{t("install.cdpMissing")}</p>}
      {err?.type.endsWith("count-check-required") && <p className="error">{t("install.checkRequired")}</p>}
      {err?.type.endsWith("cameras-required") && <p className="error">{t("install.camerasRequired")}</p>}
      {err?.type.endsWith("stream-check-failed") && <p className="error">{t("install.streamFailed")}</p>}
      {err?.type.endsWith("angle-check-required") && <p className="error">{t("install.angleRequired")}</p>}
      {err?.type.endsWith("addon-camera-needed") && <p className="error">{t("install.angle.addon")}</p>}
    </section>
  );
}

export function InstallPage() {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>(1);
  const [claim, setClaim] = useState<{ serial: string; token: string } | null>(null);
  const [kit, setKit] = useState<Kit | null>(null);
  const [shop, setShop] = useState<Shop | null>(null);
  return (
    <main>
      <h1>{t("install.title")}</h1>
      <p className="muted">{t("install.step", { n: step })}</p>
      {step === 1 && (
        <ClaimStep
          onDone={(serial, token) => {
            setClaim({ serial, token });
            setStep(2);
          }}
        />
      )}
      {step === 2 && claim && (
        <ShopStep
          serial={claim.serial}
          token={claim.token}
          onDone={(k, s) => {
            setKit(k);
            setShop(s);
            setStep(3);
          }}
        />
      )}
      {step === 3 && kit && shop && <ZonesStep kit={kit} shop={shop} onDone={() => setStep(4)} />}
      {step === 4 && kit && <CountStep kit={kit} onDone={() => setStep(5)} />}
      {step === 5 && kit && <ActivateStep kit={kit} />}
    </main>
  );
}
