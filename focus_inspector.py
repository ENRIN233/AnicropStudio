import os
import sys
import urllib.request
from pathlib import Path
import cv2
import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImageReader, QImage

DET_MODEL_URL = "https://modelscope.cn/api/v1/models/cunkai/ComfyUI_Notebook/repo?Revision=master&FilePath=buffalo_l/det_10g.onnx"

class FocusInspector:
    _det_session = None

    @classmethod
    def _get_session(cls):
        if cls._det_session is None:
            import onnxruntime as ort

            base_dir = Path(__file__).resolve().parent
            assets_dir = base_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            det_path = assets_dir / "det_10g.onnx"
            if not det_path.exists() or det_path.stat().st_size < 10000000:
                print("⚡ [FocusInspector] 正在自动下载 SCRFD-10G (约 16MB)...")
                try:
                    urllib.request.urlretrieve(DET_MODEL_URL, det_path)
                except Exception:
                    urllib.request.urlretrieve("https://huggingface.co/lithiumice/insightface/resolve/main/models/buffalo_l/det_10g.onnx", det_path)

            avail = ort.get_available_providers()
            det_providers = []
            if 'CUDAExecutionProvider' in avail:
                det_providers.append('CUDAExecutionProvider')
            det_providers.append('CPUExecutionProvider')

            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.intra_op_num_threads = min(8, os.cpu_count() or 4)

            cls._det_session = ort.InferenceSession(str(det_path), sess_options=opts, providers=det_providers)
            active_p = cls._det_session.get_providers()[0]
            print(f"🚀 [FocusInspector] 视网膜雷达点火！执行端: 【{active_p}】")

        return cls._det_session

    @staticmethod
    def _load_display_space_bgr(file_path: str):
        """
        【核心修复】用 QImageReader(autoTransform=True) 解码图片，
        与界面显示走完全相同的 EXIF 方向变换，保证：
        检测坐标空间 == 显示坐标空间 == 佳能 AF 框坐标空间。
        彻底杜绝“检测到的是侧躺图、画框画在正立图”的空间劈叉。
        返回 BGR ndarray（OpenCV 约定），失败返回 None。
        """
        reader = QImageReader(file_path)
        reader.setAutoTransform(True)
        qimg = reader.read()
        if qimg.isNull():
            return None

        qimg = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        bpl = qimg.bytesPerLine()

        buf = qimg.bits()  # PySide6 返回 memoryview
        arr = np.frombuffer(buf, dtype=np.uint8, count=bpl * h)
        arr = arr.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)
        rgb = np.array(arr)  # 拷贝脱离 Qt 缓冲区生命周期
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    @classmethod
    def _detect_faces_on_chip(cls, chip: np.ndarray) -> list:
        """
        SCRFD-10G 前向推理。
        输出结构 (fmc=3): net_outs[0:3] 分数 / [3:6] 框回归 / [6:9] 五点关键点
        该 ONNX 输出为 (N, C) 预解码格式，锚点为位置主序 (pos-major)。
        返回: [{"box": [x,y,w,h], "score": float, "kps": [(x,y)x5]}]
              kps 顺序: 左眼, 右眼, 鼻尖, 左嘴角, 右嘴角
        """
        det_session = cls._get_session()
        h, w = chip.shape[:2]

        blob = cv2.dnn.blobFromImage(chip, 1.0 / 128.0, (w, h), (127.5, 127.5, 127.5), swapRB=True)
        input_name = det_session.get_inputs()[0].name
        net_outs = det_session.run(None, {input_name: blob})

        fmc = 3
        feat_stride_fpn = [8, 16, 32]
        num_anchors = 2
        scores_list = []
        bboxes_list = []
        kpss_list = []

        for idx, stride in enumerate(feat_stride_fpn):
            scores = net_outs[idx].ravel()
            bbox_preds = net_outs[idx + fmc] * float(stride)

            kps_preds = None
            kps_idx = idx + fmc * 2
            if len(net_outs) > kps_idx:
                kps_preds = net_outs[kps_idx] * float(stride)

            feat_h, feat_w = h // stride, w // stride
            grid_y, grid_x = np.meshgrid(np.arange(feat_h), np.arange(feat_w), indexing='ij')
            anchor_centers = np.stack([grid_x.ravel() * stride, grid_y.ravel() * stride], axis=-1)
            anchor_centers = np.stack([anchor_centers] * num_anchors, axis=1).reshape((-1, 2))

            if anchor_centers.shape[0] != scores.shape[0]:
                # 模型输出锚点数与推算不一致（极端尺寸下取整差异），跳过该层
                continue

            pos_mask = scores >= 0.50  # 严苛置信度，彻底排除地毯杂质
            if not np.any(pos_mask):
                continue

            x1 = anchor_centers[:, 0] - bbox_preds[:, 0]
            y1 = anchor_centers[:, 1] - bbox_preds[:, 1]
            x2 = anchor_centers[:, 0] + bbox_preds[:, 2]
            y2 = anchor_centers[:, 1] + bbox_preds[:, 3]
            bboxes = np.stack([x1, y1, x2, y2], axis=-1)

            scores_list.append(scores[pos_mask])
            bboxes_list.append(bboxes[pos_mask])

            if kps_preds is not None:
                # kps: (N, 10) -> 5 个 (x,y)，以 anchor 中心为基准偏移
                kps = kps_preds.reshape(-1, 5, 2) + anchor_centers[:, None, :]
                kpss_list.append(kps[pos_mask])

        if not scores_list:
            return []

        all_scores = np.concatenate(scores_list)
        all_bboxes = np.concatenate(bboxes_list)
        all_kpss = np.concatenate(kpss_list) if kpss_list else None

        indices = cv2.dnn.NMSBoxes(
            all_bboxes.tolist(), all_scores.tolist(),
            score_threshold=0.50, nms_threshold=0.4
        )
        if len(indices) == 0:
            return []

        faces = []
        for i in np.array(indices).flatten():
            box = all_bboxes[i]
            x1 = max(0, box[0])
            y1 = max(0, box[1])
            x2 = min(w, box[2])
            y2 = min(h, box[3])
            entry = {"box": [x1, y1, x2 - x1, y2 - y1], "score": float(all_scores[i])}
            if all_kpss is not None:
                entry["kps"] = [(float(px), float(py)) for px, py in all_kpss[i]]
            faces.append(entry)

        return faces

    @staticmethod
    def _rect_contains_norm_point(rect: QRectF, px: float, py: float) -> bool:
        """判断归一化点是否落在归一化人脸框内（带 15% 外扩容差，焦点常在发际线/下巴边缘）"""
        mx = rect.width() * 0.15
        my = rect.height() * 0.15
        return (rect.x() - mx <= px <= rect.x() + rect.width() + mx and
                rect.y() - my <= py <= rect.y() + rect.height() + my)

    @classmethod
    def _pick_subject_face(cls, faces: list, canon_af_boxes: list,
                           scale: float, orig_w: int, orig_h: int) -> dict:
        """
        主体脸裁决:
        1. 若佳能合焦绿框存在 -> 优先选「框住合焦中心」的脸 (相机说焦点在哪就验哪张脸)
        2. 否则 -> 选面积最大的脸 (主体 Coser 通常占幅最大)
        """
        if canon_af_boxes:
            for af in canon_af_boxes:
                if not af.get("in_focus", False):
                    continue
                r = af["rect"]
                af_cx = r.x() + r.width() / 2.0
                af_cy = r.y() + r.height() / 2.0
                for f in faces:
                    bx, by, bw, bh = f["box"]
                    norm_rect = QRectF(bx / scale / orig_w, by / scale / orig_h,
                                       bw / scale / orig_w, bh / scale / orig_h)
                    if cls._rect_contains_norm_point(norm_rect, af_cx, af_cy):
                        return f

        faces.sort(key=lambda f: f["box"][2] * f["box"][3], reverse=True)
        return faces[0]

    @staticmethod
    def _eyes_from_kps(face: dict) -> tuple | None:
        """
        从五点关键点提取双眼物理中点。
        可信度校验: 眼距必须在脸宽 15%~80% 合理带内，否则视为关键点崩坏弃用。
        """
        kps = face.get("kps")
        if not kps or len(kps) < 2:
            return None
        le, re = kps[0], kps[1]
        face_w = face["box"][2]
        if face_w <= 0:
            return None
        eye_dist = abs(re[0] - le[0])
        ratio = eye_dist / face_w
        if not (0.15 <= ratio <= 0.80):
            return None
        return ((le[0] + re[0]) / 2.0, (le[1] + re[1]) / 2.0)

    @classmethod
    def locate_target(cls, file_path: str, canon_af_boxes: list, orientation: int = 1) -> dict:
        """
        极速双眼/焦点雷达：专为摄影师 R 键 250% 特写提供无损物理中心
        返回归一化坐标 [0.0, 1.0]，供视口直接居中对齐。
        注意: orientation 参数保留仅为向后兼容，图像方向已由
        QImageReader(autoTransform) 统一处理，与界面显示严格同源。
        """
        res = {
            "target_norm": (0.5, 0.5),
            "target_desc": "画面中心",
            "found_face": False,
            "debug_face_rect": None
        }

        try:
            img = cls._load_display_space_bgr(file_path)
            if img is None:
                return res
            return cls._locate_on_bgr(img, canon_af_boxes, res)
        except Exception:
            return res

    @classmethod
    def locate_target_from_qimage(cls, qimg: QImage, canon_af_boxes: list) -> dict:
        """已解码 QImage 的雷达入口（RAW 内嵌预览等），与 locate_target 同一检测管线。
        注意：传入图像必须与界面显示同源（已完成方向转正）。
        """
        res = {
            "target_norm": (0.5, 0.5),
            "target_desc": "画面中心",
            "found_face": False,
            "debug_face_rect": None
        }
        try:
            img = cls._qimage_to_bgr(qimg)
            if img is None:
                return res
            return cls._locate_on_bgr(img, canon_af_boxes, res)
        except Exception:
            return res

    @staticmethod
    def _qimage_to_bgr(qimg: QImage):
        """QImage -> BGR ndarray（处理行字节对齐，与 _load_display_space_bgr 同手法）"""
        if qimg is None or qimg.isNull():
            return None
        img2 = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = img2.width(), img2.height()
        bpl = img2.bytesPerLine()
        buf = np.frombuffer(img2.bits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)
        rgb = np.array(buf)  # 拷贝，脱离 QImage 缓冲区生命周期
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    @classmethod
    def _locate_on_bgr(cls, img, canon_af_boxes: list, res: dict) -> dict:
        """检测管线主体：BGR 图 + 佳能AF框 -> 双眼/焦点归一化锚点"""
        try:
            orig_h, orig_w = img.shape[:2]

            # 保持大长边 1280 跑人脸检测（~15ms 极速响应）
            scale = 1280.0 / max(orig_w, orig_h)
            gw = int(orig_w * scale)
            gh = int(orig_h * scale)
            pad_w = (gw + 31) // 32 * 32
            pad_h = (gh + 31) // 32 * 32

            resized = cv2.resize(img, (gw, gh))
            pad_img = np.zeros((pad_h, pad_w, 3), dtype=np.uint8)
            pad_img[:gh, :gw] = resized

            faces = cls._detect_faces_on_chip(pad_img)
            if faces:
                best_face = cls._pick_subject_face(faces, canon_af_boxes, scale, orig_w, orig_h)
                bx, by, bw, bh = best_face["box"]

                # 映射回原图物理尺度 (padding 在右下，坐标无需补偿)
                orig_fx = bx / scale
                orig_fy = by / scale
                orig_fw = bw / scale
                orig_fh = bh / scale

                # 第一优先: SCRFD 五点关键点 -> 左右眼物理中点，像素级精准
                eye_pt = cls._eyes_from_kps(best_face)
                if eye_pt is not None:
                    eye_norm_x = (eye_pt[0] / scale) / orig_w
                    eye_norm_y = (eye_pt[1] / scale) / orig_h
                else:
                    # 回退启发式: 人脸双眼黄金锚点：水平正中，垂直位于人脸框顶部往下 38%
                    eye_norm_x = (orig_fx + orig_fw * 0.5) / orig_w
                    eye_norm_y = (orig_fy + orig_fh * 0.38) / orig_h

                res["target_norm"] = (float(np.clip(eye_norm_x, 0.05, 0.95)), float(np.clip(eye_norm_y, 0.05, 0.95)))
                res["target_desc"] = "双眼已就位"
                res["found_face"] = True
                res["debug_face_rect"] = QRectF(orig_fx / orig_w, orig_fy / orig_h, orig_fw / orig_w, orig_fh / orig_h)
                return res

            # 兜底方案：如果没抓到脸，对准佳能合焦绿框
            if canon_af_boxes:
                for af in canon_af_boxes:
                    if af.get("in_focus", False):
                        r = af["rect"]
                        af_cx = r.x() + r.width() / 2.0
                        af_cy = r.y() + r.height() / 2.0
                        res["target_norm"] = (float(np.clip(af_cx, 0.05, 0.95)), float(np.clip(af_cy, 0.05, 0.95)))
                        res["target_desc"] = "佳能焦点"
                        return res

        except Exception:
            pass

        return res

    @classmethod
    def inspect(cls, file_path: str, canon_af_boxes: list, orientation: int = 1) -> dict:
        """向后兼容接口"""
        loc = cls.locate_target(file_path, canon_af_boxes, orientation)
        return {
            "verdict": loc["target_desc"],
            "color": "#38bdf8" if loc["found_face"] else "#a1a1aa",
            "score": 0.0,
            "af_hit_face": loc["found_face"],
            "eye_sharp": True,
            "target_norm": loc["target_norm"],
            "debug_face_rect": loc["debug_face_rect"]
        }
