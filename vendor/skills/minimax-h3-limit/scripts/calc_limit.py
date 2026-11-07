#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniMax H3 行数预算 → 给定图片比例+时长，算 32 倍数安全分辨率上限

两种模式（2026-10-29 依 修改_00144_ 工作流 + 三点夹逼数据重校）：
  single  单次前向（T8 导演台 / h3_batch 初版）——默认
          rows = (T_lat + 关键帧数) x (H_lat/2) x (W_lat/2) + 文本 + 音频
          无全片 clip 锚（cond 不翻倍）；关键帧 = 首尾帧硬锚(+guide)
          文本实测 ~100 行（3449 字长 prompt 与短 prompt 同价，旧 3000 保守值作废）
          音频 = 2 行 x 40 latent帧/秒（开音频时）
          参考实证：3584x832@9s(209帧,T_lat=62,K=2) = 187,188 行干净出片（hardAnchors 首尾帧+长prompt+音频开）
  tile    放大精修管线（minimax_tile_sampler）
          cond = 视频行数 x2（全片 clip 锚，17号生产实证 8896x1152@124帧5块=15.7万行）
          文本保守 3000 —— 待复核：新版节点是否仍付翻倍未见实证

公式常数（全部经生产日志验证）：
  空间: VAE 16x；DiT patch (1,2,2) → 每 latent 帧行数 = (H_lat/2) x (W_lat/2)
  时间: 前 5 像素帧 -> 2 latent 帧，其后每 17 像素帧 -> 5 latent 帧
        帧数取 17n+5 → T_lat = 5n+2   [实测 90帧->27, 124帧->37]
        注意 T_lat 跟实际帧数走：夹逼实测在 209 帧(向下取)，h3_batch 按用户公式向上取(9s=226帧,T_lat=67)
  硬上限: ~187,000 行（成功 187,188；失败下限 190,516 → 边界∈(187.2k,190.5k]，single 模式）
  安全线: single=160,000（=用户实证 3200x736@9s 档位 159,520 行取整）；tile=165,000（原值不动）
"""
import argparse, math, struct, sys

HARD_LIMIT = 187_000  # 实测成功上限 187,188（③3584x832@9s 官方fl2v）；失败下限 190,516（④3648x832 花灰彩噪）→ 边界∈(187.2k,190.5k]
SAFE_LIMIT = 165_000
AUDIO_LATENT_PER_SEC = 40
AUDIO_ROWS_PER_LATENT = 2

MODES = {
    #            clip    keyframes  text_rows  safe_limit
    "single": (False,       2,         100,   160_000),
    "tile":   (False,       0,         100,   160_000),
}
# single 安全线 160,000 = 用户实测工作点 3200x736@9s(226帧,T_lat=67,K=2)=159,520 行向上取整
# tile 2026-10-30 重大修正：clip 锚翻倍假设作废——用户实证 9248x1216@10s(238帧,6块)=13.2万行出片正常，
# 若有翻倍应为 26.9 万行必花灰。tile 与 single 同样无翻倍；17号"15.7万行"系公式回填非实测，作废。
# tile 文本行数同取 100（精修提示词为短句）。tile 安全线统一 160,000


def png_size(path):
    with open(path, "rb") as f:
        d = f.read(26)
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("不是 PNG（如需 jpg 请用 --aspect 手动给比例）")
    w, h = struct.unpack(">II", d[16:24])
    return w, h


def snap_frames(sec, fps, direction):
    raw = int(round(sec * fps))
    if raw < 5:
        raise SystemExit("时长太短")
    if direction == "down":
        n = (raw - 5) // 17
    else:
        n = -((5 - raw) // 17)  # ceil
    px = 17 * n + 5
    t_lat = 5 * n + 2
    return px, n, t_lat


def tile_w(W_lat, k, overlap):
    tw = math.ceil((W_lat + (k - 1) * overlap) / k)
    tw += tw % 2  # 对齐偶数（节点行为）
    return min(tw, W_lat)


def rows_for(H_lat, W_lat, k, overlap, t_lat, clip, n_kf, text_rows, sec):
    tw = tile_w(W_lat, k, overlap)
    per_frame = (H_lat // 2) * (tw // 2)
    r = t_lat * per_frame * (2 if clip else 1)
    if not clip:
        r += n_kf * per_frame  # 单帧关键帧（first/last[/guide]）
    r += text_rows
    r += AUDIO_ROWS_PER_LATENT * AUDIO_LATENT_PER_SEC * sec
    return r, tw


def max_canvas(aspect, k, overlap, t_lat, clip, n_kf, text_rows, sec, limit):
    """偶数步进搜最大 H_lat，使该 k 下行数 <= limit"""
    lo, hi, best = 2, 400, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid % 2:
            mid += 1
        H_px = 16 * mid
        W_px = round(H_px * aspect / 32) * 32
        W_lat = W_px // 16
        r, tw = rows_for(mid, W_lat, k, overlap, t_lat, clip, n_kf, text_rows, sec)
        if r <= limit and tw >= 8:
            best = (mid, W_px, H_px, r, tw)
            lo = mid + 2
        else:
            hi = mid - 2
    return best


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", help="PNG 路径（取宽高比）")
    src.add_argument("--aspect", type=float, help="宽高比 W/H")
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--tiles", type=int, help="指定横向块数（默认扫 4~16）")
    ap.add_argument("--overlap", type=int, default=8)
    ap.add_argument("--mode", choices=list(MODES), default="single",
                    help="single=单次前向(T8导演台/h3_batch初版,默认): 无clip锚+关键帧+文本~100行; "
                         "tile=放大精修管线: clip锚x2+文本3000")
    ap.add_argument("--no-clip-anchor", action="store_true",
                    help="强制关闭全片clip锚（single 模式本来就关；tile 模式可加此开关试验）")
    ap.add_argument("--keyframes", type=int, default=None,
                    help="无clip锚时的单帧关键帧数（默认按模式: single=2, 可按实际锚点数改，如仅首帧=1、首尾+1guide=3、首尾+2guide=4）")
    ap.add_argument("--text-rows", type=int, default=None,
                    help="文本行数（默认按模式: single=100 实测值, tile=3000 保守值）")
    ap.add_argument("--limit", type=int, default=None,
                    help="行数安全线（默认按模式: single=160000, tile=165000）")
    ap.add_argument("--snap", choices=["down", "up"], default="down")
    a = ap.parse_args()

    m_clip, m_kf, m_text, m_limit = MODES[a.mode]
    clip = False if a.no_clip_anchor else m_clip
    n_kf = a.keyframes if a.keyframes is not None else m_kf
    text_rows = a.text_rows if a.text_rows is not None else m_text
    limit = a.limit if a.limit is not None else m_limit

    if a.image:
        w, h = png_size(a.image)
        aspect = w / h
        print(f"图片: {w}x{h}  比例 {aspect:.4f}")
    else:
        aspect = a.aspect
        print(f"比例: {aspect:.4f}")

    px, n, t_lat = snap_frames(a.seconds, a.fps, a.snap)
    audio_rows = 2 * 40 * a.seconds
    print(f"时长 {a.seconds}s @ {a.fps}fps = {int(round(a.seconds*a.fps))}帧 -> snap {a.snap} "
          f"{px}帧 (17n+5, n={n}) -> T_lat={t_lat}")
    print(f"固定开销: 文本~{text_rows} + 音频~{int(audio_rows)} = ~{int(text_rows+audio_rows)}"
          f"  |  模式: {a.mode} | {'全片clip锚(cond=视频行数x2)' if clip else f'单帧关键帧x{n_kf}'}"
          f"  |  安全线 {limit} / 硬上限 {HARD_LIMIT}")
    print("-" * 100)
    head = f"{'块数':>4} {'画布(px)':>14} {'tile(latent)':>14} {'tile(px)':>12} {'行数':>9} {'余量':>7} {'百万像素':>8}"
    print(head)
    ks = [a.tiles] if a.tiles else range(1, 17)
    results = []
    for k in ks:
        b = max_canvas(aspect, k, a.overlap, t_lat, clip, n_kf, text_rows, a.seconds, limit)
        if not b:
            print(f"{k:>4}  无解（该块数下达不到安全线）")
            continue
        H_lat, W_px, H_px, r, tw = b
        W_lat = W_px // 16
        margin = (limit - r) / limit * 100
        mp = W_px * H_px / 1e6
        if k == 1:
            flag = " <-- 无缝单块上限"
        elif not results:
            flag = " <-- 最少块数方案"
        else:
            flag = ""
        print(f"{k:>4} {f'{W_px}x{H_px}':>14} {f'{W_lat}x{H_lat}':>14} "
              f"{f'{tw*16}x{H_px}':>12} {r:>9,.0f} {margin:>6.0f}% {mp:>8.2f}{flag}")
        results.append((k, W_px, H_px, r, mp))
    if len(results) > 1 and not a.tiles:
        print("-" * 100)
        one = results[0]
        print(f"无缝单块上限(限{limit}): {one[1]}x{one[2]} ({one[4]:.2f}MP, {one[3]:,.0f} 行)")
        ok = [x for x in results if (limit - x[3]) / limit >= 0.03]
        if ok:
            fast = ok[0] if ok[0][0] != 1 or len(ok) == 1 else (ok[1] if ok[0][0] == 1 and len(ok) > 1 else ok[0])
            best = max(results, key=lambda x: x[4])
            print(f"推荐(速度): {fast[0]}块 {fast[1]}x{fast[2]} ({fast[4]:.2f}MP)   "
                  f"推荐(画质): {best[0]}块 {best[1]}x{best[2]} ({best[4]:.2f}MP)")
        if limit < HARD_LIMIT:
            h1 = max_canvas(aspect, 1, a.overlap, t_lat, clip, n_kf, text_rows, a.seconds, HARD_LIMIT)
            hbest, hb_k = None, None
            for k in range(1, 17):
                hb = max_canvas(aspect, k, a.overlap, t_lat, clip, n_kf, text_rows, a.seconds, HARD_LIMIT)
                if hb and (not hbest or hb[1] * hb[2] > hbest[1] * hbest[2]):
                    hbest, hb_k = hb, k
            if h1:
                print(f"硬上限极限({HARD_LIMIT}, 无缓冲, 仅测试用): 1块 {h1[1]}x{h1[2]} ({h1[3]:,.0f}行)"
                      + (f"   最大画幅: {hb_k}块 {hbest[1]}x{hbest[2]} ({hbest[1]*hbest[2]/1e6:.1f}MP, {hbest[3]:,.0f}行)" if hbest else ""))
        print("注: 总耗时 ~ 块数 x 行数^2，块数翻倍总时间约x4；分辨率与速度自己权衡。")


if __name__ == "__main__":
    main()
