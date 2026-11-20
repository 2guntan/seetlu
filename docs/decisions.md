# Decision log

| Date | Question | Decision | Why |
| --- | --- | --- | --- |
| 2026-11-20 | Edge hardware | Rockchip RK3588 (Orange Pi 5) + Frigate rknn detector; fallback Raspberry Pi 5 + AI HAT+ | Cheapest from China, Frigate supports the NPU natively |
| 2026-11-20 | Door counting method | Two band zones (`door_out`, `door_in`) and zone-sequence logic, not pixel line crossing | Frigate publishes zone changes reliably; positions are not streamed every frame |
| 2026-11-20 | Core health metric | Revenue per served customer vs the shop's own 14–28 day baseline | Works without per-sale cash logging; robust to shop size |
| 2026-11-20 | Video in the cloud | Only requested clips (≤ 20 s, 480p) and snapshots | Privacy, data cost, CDP regime |
