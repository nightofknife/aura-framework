# node_palette.py
from PySide6.QtCore import Qt, QMimeData, QByteArray
from PySide6.QtGui import QPixmap, QDrag
from PySide6.QtWidgets import QListWidget, QListWidgetItem

class NodePalette(QListWidget):
    node_dragged = Signal(ActionDefinition, QPointF)  # 信号: action_def + 目标pos

    def __init__(self, action_defs: List[ActionDefinition], parent=None):
        super().__init__(parent)
        self.action_defs = action_defs
        self._populate()

    def _populate(self):
        self.clear()
        for defn in sorted(action_defs, key=lambda d: d.name):
            item = QListWidgetItem(defn.name)
            # 图标 (从defn或默认)
            pix = QPixmap(16, 16)
            pix.fill(defn.plugin.icon_color or QColor(100, 100, 100))  # 假设
            item.setIcon(QIcon(pix))
            item.setData(Qt.UserRole, defn)
            self.addItem(item)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        defn = item.data(Qt.UserRole)
        if not isinstance(defn, ActionDefinition):
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(defn.name)  # 或setData('aura/action', QByteArray(defn.fqid.encode()))
        drag.setMimeData(mime)

        # 预览 (拖影)
        pixmap = QPixmap(50, 50)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.drawText(10, 20, defn.name[:10])
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPointF(25, 25))  # 中心

        # 连接drop到graph
        drop_action = drag.exec(supportedActions)
        if drop_action == Qt.MoveAction:
            # 获取drop pos (从graph的dropEvent)
            pos = self.mapToGlobal(QPoint(0, 0))  # 实际需graph emit pos
            self.node_dragged.emit(defn, pos)