import os
import re
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal

class RawSorterWorker(QThread):
    """
    P0.1 RAW 分流调度后台工作线程
    - 严格只匹配并处理 .cr3 / .CR3 后缀，彻底过滤视频(.mp4)、直出图(.jpg)等杂质
    - 针对佳能 R50 适配：支持 IMG_ 与 _MG_ 色彩空间前缀容错
    - 采用 4MB 内存分块顺序流式写入，保护机械硬盘磁头不反复寻道
    """
    sig_log = Signal(str, str)             # 传递日志: (内容, 级别: INFO/SUCCESS/WARN/ERROR)
    sig_progress = Signal(int, int, str)   # 传递进度: (当前完成数, 总数, 当前文件名)
    sig_finished = Signal(dict)            # 任务结束汇报: 统计字典

    def __init__(self, jpg2_dir: str, raw_source_dir: str, cr3_dest_dir: str, 
                 tolerance_prefix: bool = True, skip_existing: bool = True):
        super().__init__()
        self.jpg2_dir = Path(jpg2_dir.strip())
        self.raw_source_dir = Path(raw_source_dir.strip())
        self.cr3_dest_dir = Path(cr3_dest_dir.strip())
        self.tolerance_prefix = tolerance_prefix
        self.skip_existing = skip_existing
        self._is_canceled = False

    def cancel(self):
        """外部调用以中止任务"""
        self._is_canceled = True

    @staticmethod
    def normalize_stem(stem: str) -> str:
        """
        抹平相机前缀差异:
        佳能 sRGB: IMG_1234 -> 1234 / Adobe RGB: _MG_1234 -> 1234
        索尼 sRGB: DSC01234 -> 01234 / Adobe RGB: _DSC1234 -> 01234
        """
        lower = stem.lower()
        if lower.startswith("img_") or lower.startswith("_mg_"):
            return lower[4:]
        if lower.startswith("dsc0"):
            return lower[4:]
        if lower.startswith("_dsc"):
            return lower[4:]
        return lower

    def run(self):
        start_time = time.time()
        self.sig_log.emit("🚀 启动 RAW 分流调度任务...", "INFO")

        # 1. 基础路径校验
        if not self.jpg2_dir.exists() or not self.jpg2_dir.is_dir():
            self.sig_log.emit(f"❌ 细筛目录不存在: {self.jpg2_dir}", "ERROR")
            self.sig_finished.emit({"success": False, "error": "细筛目录无效"})
            return

        if not self.raw_source_dir.exists() or not self.raw_source_dir.is_dir():
            self.sig_log.emit(f"❌ RAW 源目录不存在: {self.raw_source_dir}", "ERROR")
            self.sig_finished.emit({"success": False, "error": "RAW 源目录无效"})
            return

        # 2. 扫描 jpg2 细筛目录
        self.sig_log.emit(f"📂 正在扫描细筛目录: {self.jpg2_dir}", "INFO")
        valid_extensions = {".jpg", ".jpeg"}
        jpg_stems = []
        for file in self.jpg2_dir.iterdir():
            if file.is_file() and file.suffix.lower() in valid_extensions:
                jpg_stems.append(file.stem)

        total_jpg = len(jpg_stems)
        if total_jpg == 0:
            self.sig_log.emit("⚠️ 细筛目录中未找到任何 JPG 文件，任务终止。", "WARN")
            self.sig_finished.emit({"success": False, "error": "细筛目录无有效图片"})
            return

        self.sig_log.emit(f"✅ 成功索引到 {total_jpg} 张细筛照片待匹配", "SUCCESS")

        # 3. 扫描 RAW 源目录，建立 CR3 索引池（严格排除所有非 .cr3 文件）
        self.sig_log.emit(f"🔍 正在检索 RAW 源目录（严格过滤非 CR3 格式）: {self.raw_source_dir}", "INFO")
        raw_index = {}
        ignored_count = 0

        for file in self.raw_source_dir.iterdir():
            if not file.is_file():
                continue
            
            # 严格后缀检查：只认佳能 .cr3 和索尼 .arw
            if file.suffix.lower() not in {".cr3", ".arw"}:
                ignored_count += 1
                continue

            stem = file.stem
            key = self.normalize_stem(stem) if self.tolerance_prefix else stem.lower()
            raw_index[key] = file

        self.sig_log.emit(
            f"📦 源目录就绪: 索引到 {len(raw_index)} 个有效 CR3 文件（已自动过滤 {ignored_count} 个非 CR3 杂质文件）",
            "INFO"
        )

        # 4. 创建目标文件夹
        try:
            self.cr3_dest_dir.mkdir(parents=True, exist_ok=True)
            self.sig_log.emit(f"📁 确认目标输出目录: {self.cr3_dest_dir}", "INFO")
        except Exception as e:
            self.sig_log.emit(f"❌ 无法创建目标目录: {str(e)}", "ERROR")
            self.sig_finished.emit({"success": False, "error": f"创建目标目录失败: {str(e)}"})
            return

        # 5. 执行碰撞匹配与分块流式复制
        matched_tasks = []
        orphan_jpgs = []

        for stem in jpg_stems:
            key = self.normalize_stem(stem) if self.tolerance_prefix else stem.lower()
            if key in raw_index:
                src_path = raw_index[key]
                dest_path = self.cr3_dest_dir / src_path.name
                matched_tasks.append((src_path, dest_path))
            else:
                orphan_jpgs.append(stem)

        total_tasks = len(matched_tasks)
        self.sig_log.emit(f"🎯 碰撞比对完成: 命中 {total_tasks} 张，未匹配 {len(orphan_jpgs)} 张", "INFO")

        if len(orphan_jpgs) > 0:
            self.sig_log.emit(f"⚠️ 以下 JPG 未在源目录中找到对应 CR3: {', '.join(orphan_jpgs[:10])}{' ...等' if len(orphan_jpgs) > 10 else ''}", "WARN")

        # 6. 开始顺序 IO 搬运
        copied_count = 0
        skipped_count = 0
        chunk_size = 4 * 1024 * 1024  # 4MB 分块

        for idx, (src_file, dst_file) in enumerate(matched_tasks, 1):
            if self._is_canceled:
                self.sig_log.emit("🛑 任务被用户强制中止！", "WARN")
                break

            self.sig_progress.emit(idx, total_tasks, src_file.name)

            # 跳过已存在文件检查
            if self.skip_existing and dst_file.exists():
                skipped_count += 1
                self.sig_log.emit(f"⏭️ [{idx}/{total_tasks}] 已存在跳过: {dst_file.name}", "INFO")
                continue

            try:
                # 4MB 分块流式顺序读写，减轻机械盘随机 IO 压力
                with open(src_file, 'rb') as f_src, open(dst_file, 'wb') as f_dst:
                    while True:
                        if self._is_canceled:
                            break
                        chunk = f_src.read(chunk_size)
                        if not chunk:
                            break
                        f_dst.write(chunk)

                if self._is_canceled:
                    # 如果中止，清理残留未写完的文件
                    if dst_file.exists():
                        try:
                            dst_file.unlink()
                        except Exception:
                            pass
                    break

                copied_count += 1
                file_size_mb = src_file.stat().st_size / (1024 * 1024)
                self.sig_log.emit(f"✨ [{idx}/{total_tasks}] 成功搬运: {dst_file.name} ({file_size_mb:.1f} MB)", "SUCCESS")

            except Exception as e:
                self.sig_log.emit(f"❌ 写入失败 {src_file.name}: {str(e)}", "ERROR")

        elapsed_sec = max(time.time() - start_time, 0.001)
        
        summary = {
            "success": not self._is_canceled,
            "canceled": self._is_canceled,
            "total_jpg": total_jpg,
            "matched_count": total_tasks,
            "copied_count": copied_count,
            "skipped_count": skipped_count,
            "orphan_count": len(orphan_jpgs),
            "orphan_list": orphan_jpgs,
            "elapsed_sec": elapsed_sec
        }

        self.sig_finished.emit(summary)