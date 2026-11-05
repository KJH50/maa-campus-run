# 第三方组件与许可证声明（Third-Party Notices）

本项目（**MaaCampusRun**，校园跑值守）的**原创代码**采用 **GNU General Public License v3.0**（GPL-3.0，见仓库根目录 `LICENSE`；版权声明见 `NOTICE`）。
以下第三方组件、依赖与资源分别遵循其各自许可证；本项目的 GPL 授权**不改变**、也不得被解释为改变这些第三方许可证的条款。

## 1. 运行时依赖（通过 pip 安装，不随本仓库分发）

| 组件 | 来源 / 版本 | 许可证 | 说明 |
|---|---|---|---|
| MaaFw（MaaFramework 的 Python 绑定） | PyPI `MaaFw==5.15.0` | **LGPL-3.0** | 本项目通过 import 动态调用，未修改其源码；对应原生库与许可随包分发 |
| MaaAgentBinary | PyPI `MaaAgentBinary==1.0.1`（MaaFw 的传递依赖） | **AGPL-3.0** | 通过依赖链安装，未随本仓库分发 |
| numpy | PyPI `numpy`（`requirements.txt` 约束 `>=1.24`） | **BSD-3-Clause**（含 0BSD / MIT / Zlib / CC0-1.0 等组件） | 数值计算 |
| Pillow | PyPI `pillow>=10.0` | **MIT-CMU**（HPND 风格） | 图像处理与截图 |
| StrEnum | PyPI（MaaFw 依赖链） | **MIT** | 依赖链组件 |

> 以上依赖的完整许可证文本随各自 wheel 分发，可在安装后的 `site-packages` 中对应 `*.dist-info/licenses/` 目录查看。

## 2. 随本仓库分发的第三方资源

| 资源 | 路径 | 许可证 | 来源与说明 |
|---|---|---|---|
| PaddleOCR 中文 OCR 模型（`det.onnx` / `rec.onnx` / `keys.txt`） | `assets/resource/model/ocr/` | **Apache-2.0** | 来自 MaaXYZ/MaaCommonAssets（`OCR/ppocr_v5/zh_cn`）；许可全文见同目录 [`LICENSE-APACHE-2.0.txt`](assets/resource/model/ocr/LICENSE-APACHE-2.0.txt) |

分发本仓库时，请保留上述模型的来源说明与 Apache-2.0 许可文本；不得将额外限制附加到这些模型上（应保留其 Apache-2.0 许可）。

## 3. 仅参考、未复制代码的项目

| 项目 | 许可证 | 说明 |
|---|---|---|
| MaaEnd | **AGPL-3.0** | 本项目仅参考其工程结构与协议用法，**未复制其代码或资源** |

## 4. 合规提示

1. 本项目原创代码的 GPL-3.0 授权**不适用于**上述第三方组件；第三方组件按其自身许可证使用、修改与分发。
2. 依赖链中存在 **AGPL-3.0** 组件（`MaaAgentBinary`）。当前以 pip 依赖形式获取、未随仓库分发；GPLv3 与 AGPLv3 可组合，但若分发包含该组件的组合包或修改该组件，需按 AGPL-3.0 处理（含网络使用条款）。
3. 若你分发本仓库或其衍生版本，请同时保留 `LICENSE`（GPL-3.0）、`NOTICE`（版权声明）、`DISCLAIMER.md` 与本文件；衍生作品须按 GPL-3.0 兼容方式开源。
4. 历史版本：`v0.2.0` 及更早的已发布版本当时采用 PolyForm Noncommercial 1.0.0，不因本次切换而追溯变更。
