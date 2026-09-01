# Data Quality Observatory

离线订单数据质量与业务指标监控样例：`data/orders.csv` → 规则校验 → SQLite `orders` / `quarantine` → Streamlit 看板。

## 当前能力

- 质量规则：必填字段、重复订单号、日期格式、数值类型、正数量、非负订单金额。
- 质量评分：`max(0, 100 - 异常数 / 检查行数 × 100)`，并展示有效行、异常规则和异常样例。
- 业务指标：GMV、订单数、客单价、客户数、销量，支持日期范围、日趋势和商品排行。
- 异常治理：坏行进入 `quarantine`，可在 UI 下载 CSV；合格记录保留 `source_file`、`source_row`、`loaded_at` 血缘字段。
- UI 对空日期范围和空指标有明确提示，刷新按钮会重新运行本地 ETL。

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python quality.py
pytest -q
streamlit run app.py
```

打开 Streamlit 后，在左侧点击 **Refresh pipeline** 同步 CSV 变化；使用日期范围筛选趋势，异常表可下载。`metrics.sql` 可在任意 SQLite 客户端执行，查看总览、趋势、商品排行、血缘和异常分布。

## 目录

- `quality.py`：读取、校验、评分和 SQLite ETL。
- `metrics.sql`：业务指标、质量与血缘查询。
- `app.py`：Streamlit 看板；`metric_value` 提供统一数值格式化。
- `tests/`：规则、评分、异常隔离、血缘和幂等测试。

示例 CSV 当前为 10 条合格订单，GMV 为 1022.55，AOV 为 102.25；项目只处理本地文件，不访问网络。
