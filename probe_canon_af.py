import sys
import struct
from pathlib import Path

def probe_canon_af(file_path: str):
    p = Path(file_path)
    if not p.exists():
        print(f"❌ 文件不存在: {file_path}")
        return

    print(f"\n🔍 正在探测文件: {p.name}")
    print("=" * 65)

    try:
        with open(p, 'rb') as f:
            data = f.read(250000)  # 读取前 250KB

        if len(data) < 4 or data[:2] != b'\xFF\xD8':
            print("❌ 不是有效的 JPEG 图像")
            return

        # 1. 定位 APP1 (EXIF)
        idx = 2
        tiff_data = None
        endian = None

        while idx < len(data) - 4:
            if data[idx] != 0xFF:
                break
            marker = data[idx + 1]
            if marker in (0xD9, 0xDA):
                break
            length = int.from_bytes(data[idx + 2:idx + 4], 'big')
            if marker == 0xE1:
                body = data[idx + 4 : idx + 2 + length]
                if body.startswith(b'Exif\x00\x00'):
                    tiff_data = body[6:]
                    endian = '<' if tiff_data[:2] == b'II' else ('>' if tiff_data[:2] == b'MM' else None)
                    break
            idx += 2 + length

        if not tiff_data or not endian:
            print("❌ 未能定位 TIFF 头部结构")
            return

        print(f"✅ 成功定位 EXIF TIFF 结构 (字节序: {'小端 Little-Endian' if endian == '<' else '大端 Big-Endian'})")

        # 2. 定位 MakerNote (0x927C)
        ifd0_off = struct.unpack(endian + 'I', tiff_data[4:8])[0]
        makernote_off = None
        exif_sub_off = None

        num_entries = struct.unpack(endian + 'H', tiff_data[ifd0_off : ifd0_off + 2])[0]
        for i in range(num_entries):
            ep = ifd0_off + 2 + i * 12
            tag = struct.unpack(endian + 'H', tiff_data[ep : ep + 2])[0]
            val_bytes = tiff_data[ep + 8 : ep + 12]
            if tag == 0x927C:
                makernote_off = struct.unpack(endian + 'I', val_bytes)[0]
            elif tag == 0x8769:
                exif_sub_off = struct.unpack(endian + 'I', val_bytes)[0]

        if not makernote_off and exif_sub_off:
            num_sub = struct.unpack(endian + 'H', tiff_data[exif_sub_off : exif_sub_off + 2])[0]
            for i in range(num_sub):
                ep = exif_sub_off + 2 + i * 12
                tag = struct.unpack(endian + 'H', tiff_data[ep : ep + 2])[0]
                val_bytes = tiff_data[ep + 8 : ep + 12]
                if tag == 0x927C:
                    makernote_off = struct.unpack(endian + 'I', val_bytes)[0]
                    break

        if not makernote_off:
            print("❌ 未能在 EXIF 中找到 MakerNote 厂商私有数据段")
            return

        print(f"🎯 成功锁定 MakerNote 偏移位置: 0x{makernote_off:X}")

        # 3. 扫描 MakerNote 寻找 AFInfo
        mn_entries = struct.unpack(endian + 'H', tiff_data[makernote_off : makernote_off + 2])[0]
        af_tag_found = None
        af_data_bytes = None

        for i in range(mn_entries):
            ep = makernote_off + 2 + i * 12
            if ep + 12 > len(tiff_data):
                break
            tag, ftype, count = struct.unpack(endian + 'HHI', tiff_data[ep : ep + 8])
            val_bytes = tiff_data[ep + 8 : ep + 12]

            if tag in (0x003C, 0x0026, 0x0012):
                af_tag_found = tag
                off = struct.unpack(endian + 'I', val_bytes)[0]
                total_bytes = count * 2 if ftype == 3 else count * 4
                af_data_bytes = tiff_data[off : off + total_bytes]
                break

        if not af_tag_found:
            print("⚠️ 未在 MakerNote 中找到对焦数据块 (0x003C / 0x0026)")
            return

        tag_name = "AFInfo2 (0x0026)" if af_tag_found == 0x0026 else "AFInfo3 (0x003C)"
        print(f"🎉 成功捕获佳能原厂对焦数据块: 【{tag_name}】")
        print("=" * 65)

        shorts = [struct.unpack(endian + 'h', af_data_bytes[j:j+2])[0] for j in range(0, len(af_data_bytes), 2)]
        ushorts = [struct.unpack(endian + 'H', af_data_bytes[j:j+2])[0] for j in range(0, len(af_data_bytes), 2)]

        area_mode = shorts[1]
        num_points = shorts[2]
        valid_points = shorts[3]
        af_w = shorts[6]
        af_h = shorts[7]

        print(f"• 对焦模式代码 (AFAreaMode): {area_mode} (佳能 EOS R 全域主体/人眼追踪)")
        print(f"• 对焦点总数 (NumAFPoints): {num_points}")
        print(f"• 有效对焦点 (ValidAFPoints): {valid_points}")
        print(f"• 对焦基准画布 (AFCanvas): {af_w} × {af_h}")

        # 4. 深度解析 651 个分区数组与合焦位掩码
        if num_points == 651 and len(shorts) >= 2612:
            widths = shorts[8 : 8 + 651]
            heights = shorts[8 + 651 : 8 + 651 * 2]
            xs = shorts[8 + 651 * 2 : 8 + 651 * 3]
            ys = shorts[8 + 651 * 3 : 8 + 651 * 4]

            primary_idx = shorts[-1]
            print(f"• 尾部主焦点索引 (PrimaryPoint): #{primary_idx}")

            # 解析 41 个 Word 的合焦位掩码 (哪个框变绿了)
            mask_start = 8 + 651 * 4
            in_focus_indices = []
            
            for k in range(651):
                word_idx = mask_start + (k // 16)
                if word_idx < len(ushorts):
                    bit_val = (ushorts[word_idx] >> (k % 16)) & 1
                    if bit_val == 1:
                        in_focus_indices.append(k)

            print(f"• 变绿合焦对焦点 (In-Focus Points): {in_focus_indices if in_focus_indices else '位掩码未置位，扫描非零坐标...'}")

            # 寻找全部有实质坐标的框
            active_targets = []
            for k in range(651):
                is_focus = (k in in_focus_indices) or (k == primary_idx)
                if xs[k] != 0 or ys[k] != 0 or widths[k] > 0 or is_focus:
                    active_targets.append((k, xs[k], ys[k], widths[k], heights[k], is_focus))

            print(f"\n🎯 锁定激活的对焦框列表 (共 {len(active_targets)} 个):")
            for pt_id, x, y, w, h, is_f in active_targets[:6]:
                # 坐标中心偏移推导
                abs_x = (af_w / 2.0) + x
                abs_y_up = (af_h / 2.0) - y    # Y 轴向上为正
                abs_y_down = (af_h / 2.0) + y  # Y 轴向下为正

                pct_x = (abs_x / af_w) * 100
                pct_y = (abs_y_up / af_h) * 100

                status_str = "【🟢 最终合焦变绿】" if is_f else "【⚪ 追踪候选框】"
                print(f"\n  {status_str} 对焦点 #{pt_id}:")
                print(f"    - 原厂长宽: W={w} px, H={h} px")
                print(f"    - 原厂中心相对坐标: (X={x}, Y={y})")
                print(f"    - 绝对像素中心点 (Y向上): X={abs_x:.1f}, Y={abs_y_up:.1f}")
                print(f"    - 画面百分比位置: 水平 {pct_x:.1f}%, 垂直 {pct_y:.1f}%")

        print("\n" + "=" * 65)
        print("✅ 探测完毕！数据提取成功！\n")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 解析发生异常: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        candidates = list(Path(".").glob("*.jpg")) + list(Path(".").glob("*.JPG"))
        if candidates:
            target = str(candidates[0])
            print(f"未指定文件，自动使用当前目录照片: {target}")
        else:
            print("用法: python probe_canon_af.py \"你的照片路径.jpg\"")
            sys.exit(0)

    probe_canon_af(target)