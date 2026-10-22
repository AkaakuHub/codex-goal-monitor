from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox,
)

from ..configuration import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings):
        super().__init__()
        self.setWindowTitle('Codex Goal Monitorの設定')
        self.setMinimumWidth(520)
        self.value = settings
        self.webhook = QLineEdit(settings.webhook_url)
        self.webhook.setEchoMode(QLineEdit.EchoMode.Password)
        self.label = QLineEdit(settings.sender_label)
        self.label.setMaxLength(80)
        self.home = QLineEdit(settings.codex_home)
        self.command = QLineEdit(settings.codex_command)
        form = QFormLayout(self)
        form.addRow('Discord Webhook URL', self.webhook)
        form.addRow('送信元ラベル', self.label)
        form.addRow('Codexホーム', self.home)
        form.addRow('Codex CLI', self.command)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def submit(self) -> None:
        self.value = Settings(
            webhook_url=self.webhook.text().strip(),
            sender_label=self.label.text().strip(),
            codex_home=self.home.text().strip(),
            codex_command=self.command.text().strip(),
        )
        try:
            self.value.validate()
        except ValueError as error:
            QMessageBox.warning(self, '設定を確認してください', str(error))
            return
        self.accept()
