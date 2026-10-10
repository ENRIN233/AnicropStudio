# -*- coding: utf-8 -*-
"""Anicrop Studio - CR3 对焦点取证工具 (纯标准库, 任意 Python3 可跑)

用法:
    python debug_raw.py IMG_2706.CR3            # 单文件
    python debug_raw.py IMG_2706.JPG IMG_2706.CR3   # JPG/CR3 对比 (推荐)

会做的事:
  1. 对 JPG: 解析 APP1 EXIF -> 方向 / MakerNote / 0x0026(AFInfo2) / 0x003C(AFInfo3)
  2. 对 CR3: a) 抽内嵌预览 JPEG, 对它做同样的完整解析
             b) 枚举容器内独立 TIFF 块, 找 IFD0 直挂 0x0026/0x003C 的块
  每条 AFInfo 数据都会: 打印前 48 个 shorts 原始值 + 按经典布局解读 + 算出合焦框归一化坐标
把全部输出发我即可。
"""
import struct
import sys


def parse_shorts(raw, endian, n=48):
    return [struct.unpack(endian + 'h', raw[j:j + 2])[0] for j in range(0, min(len(raw), n * 2), 2)]


def read_ifd(tiff, endian, ifd_off):
    """返回 {tag: (ftype, count, value_bytes, raw_value_field)}
    value_bytes = 按偏移取出的实际数据; raw_value_field = 条目里那 4 字节原样(偏移类条目用它取偏移)"""
    out = {}
    try:
        num = struct.unpack(endian + 'H', tiff[ifd_off:ifd_off + 2])[0]
        if num <= 0 or num > 300 or ifd_off + 2 + num * 12 > len(tiff):
            return out
        tsz = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
        for k in range(num):
            ep = ifd_off + 2 + k * 12
            tag, ftype, count = struct.unpack(endian + 'HHI', tiff[ep:ep + 8])
            raw4 = tiff[ep + 8:ep + 12]
            size = tsz.get(ftype, 1) * count
            if size <= 4:
                val = tiff[ep + 8:ep + 8 + size]
            else:
                off = struct.unpack(endian + 'I', raw4)[0]
                val = tiff[off:off + size] if 0 <= off <= len(tiff) else b''
            out[tag] = (ftype, count, val, raw4)
    except Exception:
        pass
    return out


def classic_interpret(af_bytes, endian, label):
    """按经典 AFInfo2 布局解读并打印; 返回合焦框列表 [(cx,cy,w,h), ...] 归一化"""
    shorts = [struct.unpack(endian + 'h', af_bytes[j:j + 2])[0] for j in range(0, len(af_bytes) - 1, 2)]
    ushorts = [struct.unpack(endian + 'H', af_bytes[j:j + 2])[0] for j in range(0, len(af_bytes) - 1, 2)]
    print(f'  [{label}] 共 {len(shorts)} shorts')
    print(f'  前48 shorts: {shorts[:48]}')
    if len(shorts) < 8:
        print('  !! 数据太短'); return []
    size_field, mode, num, valid = shorts[0], shorts[1], shorts[2], shorts[3]
    canon_w, canon_h, af_w, af_h = shorts[4], shorts[5], shorts[6], shorts[7]
    print(f'  [经典布局] AFInfoSize={size_field} AFAreaMode={mode} NumAFPoints={num} Valid={valid}')
    print(f'             CanonImage={canon_w}x{canon_h}  AFImage={af_w}x{af_h}')
    ok = (0 < num <= 5000) and af_w > 0 and af_h > 0 and len(shorts) >= 8 + num * 4
    if not ok:
        print('  !! 经典布局解读失败 (num 越界或数据不足) —— 布局不同')
        return []
    widths = shorts[8:8 + num]
    heights = shorts[8 + num:8 + num * 2]
    xs = shorts[8 + num * 2:8 + num * 3]
    ys = shorts[8 + num * 3:8 + num * 4]
    mask_start = 8 + num * 4
    mlen = (num + 15) // 16
    primary = shorts[-1]

    def bits(start):
        r = set()
        for k in range(num):
            wi = start + k // 16
            if wi < len(ushorts) and ((ushorts[wi] >> (k % 16)) & 1):
                r.add(k)
        return r

    in_focus = bits(mask_start)
    selected = bits(mask_start + mlen)   # EOS: AFPointsSelected 紧跟 InFocus 之后
    print(f'  mask区: InFocus @short[{mask_start}..{mask_start+mlen-1}]  Selected @short[{mask_start+mlen}..{mask_start+mlen*2-1}]  primary_idx={primary}')
    print(f'  InFocus 置位索引: {sorted(in_focus)}')
    print(f'  Selected 置位索引: {sorted(selected)}')
    show = sorted(in_focus | selected | ({primary} if 0 <= primary < num else set()))[:12]
    boxes = []
    for k in show:
        tag = ('I' if k in in_focus else '-') + ('S' if k in selected else '-') + ('P' if k == primary else '-')
        cx = (af_w / 2.0 + xs[k]) / af_w
        cy = (af_h / 2.0 - ys[k]) / af_h
        bw = (widths[k] if widths[k] > 0 else 262) / af_w
        bh = (heights[k] if heights[k] > 0 else 262) / af_h
        boxes.append((round(cx, 4), round(cy, 4), round(bw, 4), round(bh, 4)))
        print(f'    点{k} [{tag}]: raw_x={xs[k]} raw_y={ys[k]} raw_w={widths[k]} raw_h={heights[k]}'
              f' -> cx={round(cx,4)} cy={round(cy,4)} w={round(bw,4)} h={round(bh,4)}')
    return boxes
    for k in sorted(in_focus)[:8]:
        cx = (af_w / 2.0 + xs[k]) / af_w
        cy = (af_h / 2.0 - ys[k]) / af_h
        bw = (widths[k] if widths[k] > 0 else 262) / af_w
        bh = (heights[k] if heights[k] > 0 else 262) / af_h
        boxes.append((round(cx, 4), round(cy, 4), round(bw, 4), round(bh, 4)))
        print(f'    点{k}: raw_x={xs[k]} raw_y={ys[k]} raw_w={widths[k]} raw_h={heights[k]}'
              f' -> cx={round(cx,4)} cy={round(cy,4)} w={round(bw,4)} h={round(bh,4)}')
    return boxes


def _dump_makernote(tiff, endian, mn_off, via):
    mn = read_ifd(tiff, endian, mn_off)
    if not mn:
        return
    print(f'  MakerNote ({via}): {len(mn)} 条目')
    for t in (0x0026, 0x003C):
        if t in mn:
            ftype, count, raw = mn[t][:3]
            print(f'  MakerNote 0x{t:04X}: ftype={ftype} count={count} 字节={len(raw)}')
            classic_interpret(raw, endian, f'MakerNote({via}) 0x{t:04X}')

def analyze_exif_tiff(tiff, endian, label):
    """对一个 TIFF 块做完整 AF 取证: IFD0 直挂 + IFD0/ExifIFD 里的 0x927C MakerNote"""
    print(f'--- {label} (endian={endian}) ---')
    ifd0_off = struct.unpack(endian + 'I', tiff[4:8])[0]
    e0 = read_ifd(tiff, endian, ifd0_off)
    print(f'  IFD0 tags: {[hex(t) for t in sorted(e0)]}')
    if 0x0112 in e0:
        ov = struct.unpack(endian + 'H', e0[0x0112][2][:2])[0]
        print(f'  方向(0x0112) = {ov}')
    # 路径 A1: IFD0 里的 MakerNote 指针
    if 0x927C in e0:
        mn_off = struct.unpack(endian + 'I', e0[0x927C][3])[0]
        _dump_makernote(tiff, endian, mn_off, 'IFD0:0x927C')
    # 路径 A2: ExifIFD 里的 MakerNote 指针 (JPG 常见)
    if 0x8769 in e0:
        sub_off = struct.unpack(endian + 'I', e0[0x8769][3])[0]
        sub = read_ifd(tiff, endian, sub_off)
        print(f'  ExifIFD(0x8769): {len(sub)} 条目, 有0x927C={0x927C in sub}')
        if 0x927C in sub:
            mn_off = struct.unpack(endian + 'I', sub[0x927C][3])[0]
            _dump_makernote(tiff, endian, mn_off, 'ExifIFD:0x927C')
    # 路径 B: IFD0 直挂 (CR3 独立块)
    for t in (0x0026, 0x003C):
        if t in e0:
            ftype, count, raw = e0[t][:3]
            print(f'  IFD0 直挂 0x{t:04X}: ftype={ftype} count={count} 字节={len(raw)}')
            classic_interpret(raw, endian, f'IFD0直挂 0x{t:04X}')


def analyze_jpeg_bytes(data, label):
    print(f'=== {label} ===')
    if data[:2] != b'\xff\xd8':
        print('  不是 JPEG'); return
    idx, found = 2, False
    while idx < len(data) - 4:
        if data[idx] != 0xFF:
            break
        marker = data[idx + 1]
        if marker in (0xD9, 0xDA):
            break
        length = int.from_bytes(data[idx + 2:idx + 4], 'big')
        if marker == 0xE1:
            body = data[idx + 4:idx + 2 + length]
            if body.startswith(b'Exif\x00\x00'):
                tiff = body[6:]
                endian = '<' if tiff[:2] == b'II' else ('>' if tiff[:2] == b'MM' else None)
                if endian:
                    found = True
                    analyze_exif_tiff(tiff, endian, f'{label} APP1/EXIF')
        idx += 2 + length
    if not found:
        print('  未找到 EXIF')


def iter_tiff_candidates(data):
    """枚举容器内全部 TIFF 候选 (Exif\\0\\0 标记 + II*/MM 魔数)"""
    seen = set()
    marks = []
    pos = 0
    while True:
        i = data.find(b'Exif\x00\x00', pos)
        if i < 0:
            break
        marks.append(i + 6); pos = i + 6
    for magic in (b'II*\x00', b'MM\x00*'):
        pos = 0
        while True:
            i = data.find(magic, pos)
            if i < 0:
                break
            marks.append(i); pos = i + 2
    for off in marks[:256]:
        if off in seen or off + 8 > len(data):
            continue
        seen.add(off)
        tiff = data[off:]
        endian = '<' if tiff[:2] == b'II' else ('>' if tiff[:2] == b'MM' else None)
        if not endian:
            continue
        try:
            ifd = struct.unpack(endian + 'I', tiff[4:8])[0]
            num = struct.unpack(endian + 'H', tiff[ifd:ifd + 2])[0]
            if 0 < num <= 200 and ifd + 2 + num * 12 <= len(tiff):
                yield tiff, endian
        except Exception:
            continue


def scan_af_signatures(path):
    """全文件扫描合法 AFInfo2 头签名: [size, mode<=25, num 5..5000, valid, W, H, W, H]
    用于发现因基址偏移而藏起来的第二份 AFInfo2 记录"""
    data = open(path, 'rb').read(96 * 1024 * 1024)
    print('[C] 全文件 AFInfo2 签名扫描:')
    hits = 0
    for off in range(0, len(data) - 32, 2):
        try:
            v = struct.unpack('<8h', data[off:off + 16])
        except Exception:
            break
        num = v[2]
        if not (5 <= num <= 5000):
            continue
        if not (0 <= v[1] <= 25):
            continue
        if not (v[4] == v[6] and v[5] == v[7] and 500 < v[4] < 20000 and 500 < v[5] < 20000):
            continue
        need = 8 + num * 4 + ((num + 15) // 16) * 2 + 2
        if off + need * 2 > len(data):
            continue
        hits += 1
        print(f'  -- 命中 @0x{off:X}: size={v[0]} mode={v[1]} num={num} valid={v[3]} img={v[4]}x{v[5]}')
        classic_interpret(data[off:off + need * 2], '<', f'签名命中@0x{off:X}')
    if not hits:
        print('  (无命中)')

def analyze_cr3(path):
    print(f'=== {path} (CR3) ===')
    data = open(path, 'rb').read(96 * 1024 * 1024)

    # A) 内嵌预览 JPEG
    best, pos = b'', 0
    while pos < len(data) - 4:
        soi = data.find(b'\xff\xd8\xff', pos)
        if soi < 0:
            break
        eoi = data.find(b'\xff\xd9', soi + 3)
        if eoi < 0:
            break
        seg = data[soi:eoi + 2]
        if len(seg) > len(best):
            best = seg
        pos = eoi + 2
    print(f'[A] 内嵌预览 JPEG: {len(best)} 字节')
    if best:
        analyze_jpeg_bytes(best, '内嵌预览')

    # B) 独立 TIFF 块
    print('[B] 容器内独立 TIFF 块:')
    for i, (tiff, endian) in enumerate(iter_tiff_candidates(data)):
        try:
            ifd0 = struct.unpack(endian + 'I', tiff[4:8])[0]
            e0 = read_ifd(tiff, endian, ifd0)
            if 0x0026 in e0 or 0x003C in e0:
                print(f'  -- 候选#{i}: {len(e0)} 条目, 直挂 AFInfo')
                analyze_exif_tiff(tiff, endian, f'候选#{i}')
        except Exception:
            continue

    # C) 全文件签名扫描 (找藏起来的第二份 AFInfo2)
    scan_af_signatures(path)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    for p in args:
        print('=' * 70)
        low = p.lower()
        if low.endswith(('.cr3', '.cr2', '.arw', '.nef', '.dng', '.orf', '.rw2')):
            analyze_cr3(p)
        else:
            analyze_jpeg_bytes(open(p, 'rb').read(4 * 1024 * 1024), p)
    print('=' * 70)
    print('对比提示: JPG 的 [经典布局] 行应该完全合理; 内嵌预览和 CR3 独立块')
    print('哪一份的 NumAFPoints/AFImage 对不上、前48shorts 长什么样, 发我即可。')


if __name__ == '__main__':
    main()
