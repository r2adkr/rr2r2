import sys
import os
import subprocess
import platform
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
import fitz  # PyMuPDF
from PIL import Image
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, 
    QPushButton, QVBoxLayout, QHBoxLayout, QFrame, 
    QFileDialog, QProgressBar, QComboBox, 
    QStackedWidget, QDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint
from PyQt5.QtGui import QColor, QPalette

# 전문 스튜디오 스타일 QSS (다크 프로페셔널 테마)
STUDIO_PRO_QSS = """
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QFrame#TitleBar {
    background-color: #252526;
    border-bottom: 1px solid #2d2d2d;
}

QPushButton#WindowBtn {
    background-color: transparent;
    color: #a0a0a0;
    border: none;
    font-weight: bold;
    font-size: 14px;
    padding: 4px 10px;
    border-radius: 4px;
}

QPushButton#WindowBtn:hover {
    background-color: #383838;
    color: #ffffff;
}

QPushButton#CloseBtn:hover {
    background-color: #e81123;
    color: #ffffff;
}

QFrame#Sidebar {
    background-color: #252526;
    border-right: 1px solid #2d2d2d;
}

QPushButton#NavButton {
    background-color: transparent;
    color: #a0a0a0;
    border: none;
    border-radius: 6px;
    text-align: left;
    padding: 10px 14px;
    font-weight: 600;
}

QPushButton#NavButton:hover {
    background-color: #2a2d2e;
    color: #ffffff;
}

QPushButton#NavButton[active="true"] {
    background-color: #0d6efd;
    color: #ffffff;
}

QFrame#ContentCard {
    background-color: #2b2b2b;
    border: 1px solid #383838;
    border-radius: 10px;
}

QLabel {
    background-color: transparent;
    color: #cccccc;
    font-weight: 500;
}

QLabel#HeaderTitle {
    background-color: transparent;
    font-size: 18px;
    font-weight: 700;
    color: #ffffff;
}

QLabel#HeaderSubtitle {
    background-color: transparent;
    font-size: 12px;
    color: #999999;
}

QLineEdit, QComboBox {
    background-color: #1f1f1f;
    border: 1px solid #414141;
    border-radius: 6px;
    padding: 8px 12px;
    color: #ffffff;
    selection-background-color: #0d6efd;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #0d6efd;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QPushButton#PrimaryBtn {
    background-color: #0d6efd;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 10px 20px;
    font-weight: 600;
}

QPushButton#PrimaryBtn:hover {
    background-color: #0b5ed7;
}

QPushButton#SecondaryBtn {
    background-color: #383838;
    color: #ffffff;
    border: 1px solid #4d4d4d;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
}

QPushButton#SecondaryBtn:hover {
    background-color: #454545;
}

QProgressBar {
    border: 1px solid #414141;
    border-radius: 6px;
    background-color: #1f1f1f;
    text-align: center;
    color: #ffffff;
    font-weight: 600;
    height: 18px;
}

QProgressBar::chunk {
    background-color: #0d6efd;
    border-radius: 5px;
}
"""

class CustomStudioDialog(QDialog):
    def __init__(self, title, message):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.resize(380, 210)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        card = QFrame()
        card.setObjectName("ContentCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("background-color: transparent; font-size: 16px; font-weight: 700; color: #ffffff;")
        card_layout.addWidget(lbl_title)
        
        lbl_msg = QLabel(message)
        lbl_msg.setStyleSheet("background-color: transparent; font-size: 13px; color: #cccccc; line-height: 140%;")
        lbl_msg.setWordWrap(True)
        card_layout.addWidget(lbl_msg)
        
        card_layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("확인", objectName="PrimaryBtn")
        ok_btn.setFixedWidth(90)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        card_layout.addLayout(btn_layout)
        layout.addWidget(card)


class CompressWorker(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, input_path, output_path, garbage_level, preset_index, lossy_mode, quality_val, resize_enabled=False, max_dimension=1500):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.garbage_level = garbage_level
        self.preset_index = preset_index
        self.lossy_mode = lossy_mode
        self.quality_val = quality_val

    def process_single_image(self, doc, xref, smask):
        try:
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            
            if len(image_bytes) < 5000:
                return
                
            image = Image.open(io.BytesIO(image_bytes))
            
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                background = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                background.paste(image, mask=image.split()[-1])
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
                
            output_buffer = io.BytesIO()
            image.save(output_buffer, format="JPEG", quality=self.quality_val, optimize=True)
            compressed_bytes = output_buffer.getvalue()
            
            if smask == 0:
                doc.update_stream(xref, compressed_bytes)
        except Exception:
            pass

    def run(self):
        try:
            doc = fitz.open(self.input_path)
            total_pages = len(doc)
            
            if self.lossy_mode:
                # 모든 페이지에서 압축 대상 이미지 목록 수집
                image_tasks = []
                for page_idx in range(total_pages):
                    page = doc[page_idx]
                    image_list = page.get_images(full=True)
                    for img_info in image_list:
                        xref = img_info[0]
                        smask = img_info[1]
                        image_tasks.append((xref, smask))
                
                total_images = len(image_tasks)
                if total_images > 0:
                    completed_count = 0
                    # 멀티스레딩(ThreadPoolExecutor)으로 병렬 이미지 압축 처리
                    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
                        futures = {executor.submit(self.process_single_image, doc, xref, smask): xref for xref, smask in image_tasks}
                        for future in as_completed(futures):
                            completed_count += 1
                            progress = int((completed_count / total_images) * 60)
                            self.progress_signal.emit(progress)
                else:
                    self.progress_signal.emit(60)
            else:
                self.progress_signal.emit(60)
            
            self.progress_signal.emit(70)
            
            clean_val = False if self.preset_index == 2 else True
            
            doc.save(
                self.output_path, 
                garbage=self.garbage_level, 
                deflate=True, 
                clean=clean_val
            )
            doc.close()
            
            self.progress_signal.emit(100)
            
            orig_size = os.path.getsize(self.input_path) / (1024 * 1024)
            comp_size = os.path.getsize(self.output_path) / (1024 * 1024)
            saved_pct = ((orig_size - comp_size) / orig_size) * 100 if orig_size > 0 else 0
            
            msg = f"• 원본 용량: {orig_size:.2f} MB\n• 최적화 용량: {comp_size:.2f} MB\n• 용량 절감: {saved_pct:.1f}% 감소"
            self.finished_signal.emit(True, msg)
            
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class PDFStudioApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.initUI()
        self.old_pos = QPoint()
        
    def initUI(self):
        self.resize(760, 520)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        title_bar = QFrame()
        title_bar.setObjectName("TitleBar")
        title_bar.setFixedHeight(35)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 4, 0)
        
        title_text = QLabel("PDF Optimizer Studio Pro v2.8 (Fast)")
        title_text.setStyleSheet("background-color: transparent; color: #999999; font-weight: 600; font-size: 11px;")
        title_layout.addWidget(title_text)
        title_layout.addStretch()
        
        btn_minimize = QPushButton("—")
        btn_minimize.setObjectName("WindowBtn")
        btn_minimize.clicked.connect(self.showMinimized)
        
        btn_close = QPushButton("✕")
        btn_close.setObjectName("WindowBtn")
        btn_close.setObjectName("CloseBtn")
        btn_close.clicked.connect(self.close)
        
        title_layout.addWidget(btn_minimize)
        title_layout.addWidget(btn_close)
        main_layout.addWidget(title_bar)
        
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 20, 14, 20)
        sidebar_layout.setSpacing(6)
        
        logo_label = QLabel("STUDIO PRO")
        logo_label.setStyleSheet("background-color: transparent; font-size: 11px; font-weight: 800; color: #777777; margin-bottom: 8px; padding-left: 4px;")
        sidebar_layout.addWidget(logo_label)
        
        self.btn_smart = QPushButton("스마트 압축")
        self.btn_smart.setObjectName("NavButton")
        self.btn_smart.setProperty("active", "true")
        self.btn_smart.clicked.connect(lambda: self.switch_page(0))
        
        self.btn_custom = QPushButton("고급 설정")
        self.btn_custom.setObjectName("NavButton")
        self.btn_custom.setProperty("active", "false")
        self.btn_custom.clicked.connect(lambda: self.switch_page(1))
        
        sidebar_layout.addWidget(self.btn_smart)
        sidebar_layout.addWidget(self.btn_custom)
        sidebar_layout.addStretch()
        
        body_layout.addWidget(sidebar)
        
        self.stack = QStackedWidget()
        
        page_smart = QWidget()
        p1_layout = QVBoxLayout(page_smart)
        p1_layout.setContentsMargins(24, 24, 24, 24)
        
        card1 = QFrame()
        card1.setObjectName("ContentCard")
        c1_layout = QVBoxLayout(card1)
        c1_layout.setContentsMargins(24, 24, 24, 24)
        c1_layout.setSpacing(14)
        
        c1_layout.addWidget(QLabel("PDF 스마트 압축", objectName="HeaderTitle"))
        c1_layout.addWidget(QLabel("빠르고 간단하게 PDF를 압축할 수 있습니다.", objectName="HeaderSubtitle"))
        
        c1_layout.addWidget(QLabel("원본 PDF 파일"))
        h_file = QHBoxLayout()
        self.input_path_input = QLineEdit()
        self.input_path_input.setPlaceholderText("파일을 선택하세요...")
        self.browse_btn = QPushButton("파일 검색", objectName="SecondaryBtn")
        self.browse_btn.clicked.connect(self.select_input_file)
        h_file.addWidget(self.input_path_input)
        h_file.addWidget(self.browse_btn)
        c1_layout.addLayout(h_file)
        
        c1_layout.addWidget(QLabel("저장 위치"))
        h_save = QHBoxLayout()
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("저장될 경로...")
        self.save_browse_btn = QPushButton("경로 변경", objectName="SecondaryBtn")
        self.save_browse_btn.clicked.connect(self.select_output_file)
        h_save.addWidget(self.output_path_input)
        h_save.addWidget(self.save_browse_btn)
        c1_layout.addLayout(h_save)
        
        c1_layout.addSpacing(6)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        c1_layout.addWidget(self.progress_bar)
        
        self.compress_btn = QPushButton("압축 및 최적화 실행", objectName="PrimaryBtn")
        self.compress_btn.clicked.connect(self.start_compression)
        c1_layout.addWidget(self.compress_btn)
        
        p1_layout.addWidget(card1)
        self.stack.addWidget(page_smart)
        
        page_custom = QWidget()
        p2_layout = QVBoxLayout(page_custom)
        p2_layout.setContentsMargins(24, 24, 24, 24)
        
        card2 = QFrame()
        card2.setObjectName("ContentCard")
        c2_layout = QVBoxLayout(card2)
        c2_layout.setContentsMargins(24, 24, 24, 24)
        c2_layout.setSpacing(14)
        
        c2_layout.addWidget(QLabel("고급 파라미터 및 손실 압축", objectName="HeaderTitle"))
        c2_layout.addWidget(QLabel("어도비처럼 내부 이미지 화질을 낮춰 용량을 극적으로 줄입니다.", objectName="HeaderSubtitle"))
        
        c2_layout.addWidget(QLabel("이미지 압축 모드"))
        self.lossy_combo = QComboBox()
        self.lossy_combo.addItems([
            "고급 손실 압축 적용 (용량 대폭 감소 / 추천)", 
            "무손실 압축 유지 (화질 100% 보존)"
        ])
        self.lossy_combo.currentIndexChanged.connect(self.on_setting_changed)
        c2_layout.addWidget(self.lossy_combo)
        
        c2_layout.addWidget(QLabel("이미지 화질 프리셋 (Lossy Quality)"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "표준 압축 (화질 우수 / 80% 퀄리티)", 
            "강력 압축 (용량 최소화 / 60% 퀄리티)"
        ])
        self.quality_combo.currentIndexChanged.connect(self.on_setting_changed)
        c2_layout.addWidget(self.quality_combo)
        
        c2_layout.addWidget(QLabel("가비지 컬렉션 레벨"))
        self.garbage_combo = QComboBox()
        self.garbage_combo.addItems(["Level 4 (최대 객체 소각)", "Level 2 (표준)", "Level 1 (최소)"])
        self.garbage_combo.currentIndexChanged.connect(self.on_setting_changed)
        c2_layout.addWidget(self.garbage_combo)
        
        c2_layout.addStretch()
        p2_layout.addWidget(card2)
        self.stack.addWidget(page_custom)
        
        body_layout.addWidget(self.stack)
        main_layout.addLayout(body_layout)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = event.globalPos() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPos()

    def switch_page(self, index):
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.btn_smart.setProperty("active", "true")
            self.btn_custom.setProperty("active", "false")
        else:
            self.btn_smart.setProperty("active", "false")
            self.btn_custom.setProperty("active", "true")
        self.btn_smart.style().unpolish(self.btn_smart)
        self.btn_smart.style().polish(self.btn_smart)
        self.btn_custom.style().unpolish(self.btn_custom)
        self.btn_custom.style().polish(self.btn_custom)

    def select_input_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "PDF 파일 선택", "", "PDF Files (*.pdf)")
        if file_name:
            self.input_path_input.setText(file_name)
            dir_name, base_name = os.path.split(file_name)
            name, ext = os.path.splitext(base_name)
            default_out = os.path.join(dir_name, f"{name}_optimized{ext}")
            self.output_path_input.setText(default_out)
            
            self.progress_bar.setValue(0)
            self.progress_bar.hide()

    def select_output_file(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "저장할 PDF 경로", "", "PDF Files (*.pdf)")
        if file_name:
            self.output_path_input.setText(file_name)

    def on_setting_changed(self):
        self.progress_bar.setValue(0)
        self.progress_bar.hide()

    def start_compression(self):
        input_path = self.input_path_input.text().strip()
        output_path = self.output_path_input.text().strip()
        
        if not input_path or not os.path.exists(input_path):
            CustomStudioDialog("경고", "유효한 원본 PDF 파일을 선택해주세요.").exec_()
            return
        if not output_path:
            CustomStudioDialog("경고", "저장할 경로를 설정해주세요.").exec_()
            return
            
        lossy_mode = (self.lossy_combo.currentIndex() == 0)
        quality_val = 60 if self.quality_combo.currentIndex() == 1 else 80
        
        garbage_mapping = {0: 4, 1: 2, 2: 1}
        garbage_val = garbage_mapping.get(self.garbage_combo.currentIndex(), 4)
            
        self.compress_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.save_browse_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.worker = CompressWorker(input_path, output_path, garbage_val, 0, lossy_mode, quality_val)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.compression_finished)
        self.worker.start(QThread.HighPriority)

    def update_progress(self, val):
        self.progress_bar.setValue(val)

    def compression_finished(self, success, message):
        self.compress_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.save_browse_btn.setEnabled(True)
        
        if success:
            self.progress_bar.setValue(100)
            output_path = self.output_path_input.text().strip()
            
            CustomStudioDialog("최적화 완료", f"PDF 압축이 완료되었습니다!\n\n{message}").exec_()
            self.reveal_in_explorer(output_path)
        else:
            self.progress_bar.hide()
            CustomStudioDialog("작업 실패", f"오류가 발생했습니다:\n{message}").exec_()

    def reveal_in_explorer(self, path):
        if not path or not os.path.exists(path):
            return
        
        norm_path = os.path.normpath(path)
        system = platform.system()
        
        try:
            if system == "Windows":
                subprocess.run(['explorer', '/select,', norm_path])
            elif system == "Darwin":
                subprocess.run(['open', '-R', norm_path])
            else:
                dirname = os.path.dirname(norm_path)
                subprocess.run(['xdg-open', dirname])
        except Exception:
            pass

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, QColor(224, 224, 224))
    app.setPalette(palette)
    
    app.setStyleSheet(STUDIO_PRO_QSS)
    window = PDFStudioApp()
    window.show()
    sys.exit(app.exec_())