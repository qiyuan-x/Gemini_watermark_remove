# Gemini 水印去除工具

使用数学精确的反向 Alpha 混合算法的 Gemini AI 图片水印去除工具。

> 网页端建议使用 **Voyager**：https://github.com/Nagi-ovo/gemini-voyager
> 
> 参考项目：https://github.com/GargantuaX/gemini-watermark-remover

## 使用方法

### 直接运行 Python 脚本

1. 安装依赖：

```bash
pip install Pillow numpy
```

1. 运行程序：

```bash
python Gemini_watermark_remove.py
```

### 打包成 EXE

1. 安装打包依赖：

```bash
pip install -r requirements.txt
```

1. 使用 PyInstaller 打包：

```bash
pyinstaller build.spec
```

打包后的 EXE 文件会出现在 `dist` 目录中。

## 功能

- 单个文件处理
- 文件夹批量处理
- 自动检测水印尺寸（48×48 或 96×96）
- 基于数学算法的无损去除

## 项目结构

```
Gemini_watermark_remove/
├── Gemini_watermark_remove.py    # 主程序
├── bg_48.png                      # 48×48 水印背景
├── bg_96.png                      # 96×96 水印背景
├── requirements.txt               # 依赖列表
├── build.spec                     # PyInstaller 打包配置
└── README.md                       # 说明文档
```

## 配置文件位置

配置文件保存在以下位置（不会在程序目录产生文件夹）：

- Windows: `%APPDATA%\GeminiWatermarkRemover\config.json`
- macOS: `~/Library/Application Support/GeminiWatermarkRemover/config.json`
- Linux: `~/.config/GeminiWatermarkRemover/config.json`

