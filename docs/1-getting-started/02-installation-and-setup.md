# 2. 安装与设置

本指南将引导你完成 Aura 框架的安装和初始设置。按照以下步骤，你将能够快速地在本地环境中运行 Aura。

## 1. 环境要求

在开始之前，请确保你的开发环境中安装了以下软件：

*   **Python**: Aura 需要 Python 3.9 或更高版本。你可以通过在终端运行 `python --version` 来检查你的 Python 版本。
*   **Git**: 用于从 GitHub 克隆 Aura 的代码仓库。

## 2. 克隆代码仓库

首先，使用 `git` 命令将 Aura 的官方代码仓库克隆到你的本地机器上：

```bash
git clone https://github.com/your-repo/aura.git
cd aura
```

请将 `https://github.com/your-repo/aura.git` 替换为实际的代码仓库地址。

## 3. 安装依赖

Aura 使用 `pip` 来管理项目依赖。在代码仓库的根目录下，运行以下命令来安装所有必需的 Python 包：

```bash
pip install -r requirements.txt
```

这个命令会读取 `requirements.txt` 文件，并自动下载和安装所有依赖项。请确保你的 `pip` 是最新版本，以避免潜在的安装问题。

## 4. 启动服务

所有依赖安装完成后，你就可以启动 Aura 的核心服务了。在项目根目录下，运行 `main.py` 脚本：

```bash
python main.py
```

如果一切顺利，你将在终端看到类似以下的输出，这表明 Aura 的 API 服务器和调度器已经成功启动：

```
[INFO] Aura Scheduler has started.
[INFO] API Server is running at http://127.0.0.1:8000
```

## 5. 访问 Web UI

服务启动后，打开你的浏览器并访问以下地址，即可看到 Aura 的 Web 用户界面：

[http://127.0.0.1:8000/ui/](http://127.0.0.1:8000/ui/)

默认情况下，API 服务器会监听 `8000` 端口。你可以在 Web UI 上看到已加载的 Plans，手动触发任务，并实时查看任务的执行日志。

## 下一步

恭喜你，Aura 已经在你的本地环境中成功运行！现在，你可以继续阅读下一章节，学习如何创建并执行你的第一个自动化任务。
