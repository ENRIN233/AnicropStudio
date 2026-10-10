# -*- coding: utf-8 -*-
"""
FocusInspector 现场取证脚本
用法: python debug_focus.py "D:/照片目录/IMG_2715.JPG"
输出: 控制台检测明细 + 同目录下 debug_annotated.jpg 标注图
"""
import sys
from pathlib import Path
import cv2
import numpy as np

from focus_inspector import FocusInspector
from album import extract_canon_af_points, extract_exif_thumb_and_orientation


def main():
    if len(sys.argv) < 2:
        print('用法: python debug_focus.py "照片路径.jpg"')
        return
    file_path = sys.argv[1]

    _, orientation = extract_exif_thumb_and_orientation(file_path)
    af_boxes = extract_canon_af_points(file_path, orientation)
    print(f"EXIF Orientation = {orientation}")
    print(f"佳能 AF 框数量 = {len(af_boxes)}")
    for i, af in enumerate(af_boxes):
        r = af["rect"]
        print(f"  AF#{i}: in_focus={af['in_focus']} 归一化中心=({r.x()+r.width()/2:.3f}, {r.y()+r.height()/2:.3f})")

    file_bytes = np.fromfile(file_path, dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if orientation == 6:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif orientation == 8:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif orientation == 3:
        img = cv2.rotate(img, cv2.ROTATE_180)
    orig_h, orig_w = img.shape[:2]
    print(f"旋转后原图尺寸: {orig_w} x {orig_h}")

    scale = 1280.0 / max(orig_w, orig_h)
    gw, gh = int(orig_w * scale), int(orig_h * scale)
    pad_w, pad_h = (gw + 31) // 32 * 32, (gh + 31) // 32 * 32
    resized = cv2.resize(img, (gw, gh))
    pad_img = np.zeros((pad_h, pad_w, 3), dtype=np.uint8)
    pad_img[:gh, :gw] = resized

    faces = FocusInspector._detect_faces_on_chip(pad_img)
    print(f"\n检测到人脸数: {len(faces)}")
    for i, f in enumerate(faces):
        bx, by, bw, bh = f["box"]
        ox, oy, ow, oh = bx/scale, by/scale, bw/scale, bh/scale
        eye = FocusInspector._eyes_from_kps(f)
        eye_str = f"({eye[0]/scale:.0f}, {eye[1]/scale:.0f})" if eye else "关键点不可信->回退38%"
        print(f"  脸#{i}: score={f['score']:.3f} 原图框=({ox:.0f},{oy:.0f},{ow:.0f}x{oh:.0f}) 双眼点={eye_str}")

    loc = FocusInspector.locate_target(file_path, af_boxes, orientation)
    print(f"\n最终裁决: {loc['target_desc']}  锚点=({loc['target_norm'][0]:.3f}, {loc['target_norm'][1]:.3f})  found_face={loc['found_face']}")

    # 标注图
    vis = resized.copy()
    for i, f in enumerate(faces):
        bx, by, bw, bh = [int(v) for v in f["box"]]
        cv2.rectangle(vis, (bx, by), (bx+bw, by+bh), (0, 0, 255), 2)
        cv2.putText(vis, f"#{i} {f['score']:.2f}", (bx, max(0, by-6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
        for j, (px, py) in enumerate(f.get("kps", [])):
            cv2.circle(vis, (int(px), int(py)), 4, (255, 255, 0), -1)
    if loc["debug_face_rect"] is not None:
        r = loc["debug_face_rect"]
        x = int(r.x()*gw); y = int(r.y()*gh); w = int(r.width()*gw); h = int(r.height()*gh)
        cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 255, 0), 3)
    ax = int(loc["target_norm"][0]*gw); ay = int(loc["target_norm"][1]*gh)
    cv2.drawMarker(vis, (ax, ay), (255, 0, 255), cv2.MARKER_CROSS, 40, 3)

    out = str(Path(file_path).parent / "debug_annotated.jpg")
    cv2.imwrite(out, vis)
    print(f"\n标注图已保存: {out}")
    print("（绿框=最终选中的主体脸, 红框=全部候选脸, 青色点=五点关键点, 紫十字=最终锚点）")


if __name__ == "__main__":
    main()
