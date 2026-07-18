# packing-system

装箱算法 + 实时可视化（核心代码仓库）。

运行时产生的接口 JSON、Excel 测试集、日志、导出方案等 **不在本仓库**，默认放在同级目录：

```text
A装箱和可视化/
├── packing-system/       ← 本仓库（只含源码）
└── packing-workspace/    ← 本地数据区（勿提交 Git）
    ├── data/             # Excel / BMS
    ├── input/            # 接口拉取 raw 等
    ├── output/           # 装箱方案 JSON
    └── runtime/          # UI 日志与 exports
```

也可用环境变量覆盖数据根目录：

```bat
set PACKING_WORKSPACE=D:\path\to\packing-workspace
```

## 目录

| 路径 | 说明 |
|------|------|
| `packing/` | 装箱算法、`run_packing.py`、`run_wcs_service.py` |
| `ui/` | PyQt 实时看板（推荐 `realtime_dashboard_v3_clean.py`） |
| `config/packing_config.yaml` | 默认配置模板（密码请用本地覆盖，勿提交真实口令） |
| `tools/windows/` | 启动脚本 |
| `docs/` | 说明文档 |

## 环境

需要本机 Python（建议 3.12）。**不需要**仓库内虚拟环境。

```bat
pip install -r requirements.txt
pip install -r requirements-ui.txt
```

## 启动

可视化（推荐）：

```bat
tools\windows\start_realtime_dashboard_v3_clean.bat
```

或：

```bat
python ui\realtime_dashboard_v3_clean.py --project .
```

命令行装箱（Excel，相对 `packing-workspace/data`）：

```bat
python packing\run_packing.py --config config\packing_config.yaml
```

WCS 接口常驻：

```bat
python packing\run_wcs_service.py --config config\packing_config.yaml
```

## 配置注意

- `config/packing_config.yaml` 里 `database.password` 请改成 `CHANGE_ME` 后，在本机复制为 `config/packing_config.local.yaml` 填真实密码（已被 `.gitignore` 忽略）。
- `data_source.input_dir: input` 对应 `packing-workspace/input/`。
