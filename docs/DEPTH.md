# 碎玻璃配载单深度登记

料场配载员按磅单和实验抽样复算干料，再根据车次配比和分级证据签单。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 磅单采集 | 检查净重、重复或冲突单号 | `GET /api/weighing/{source}` | `app/modules/m1_weighing/service.py` | `tests/test_weighing.py` |
| M2 含水抽样 | 复核上下层及加权含水 | `GET /api/moisture/{source}` | `app/modules/m2_moisture/service.py` | `tests/test_moisture.py` |
| M3 色级判定 | 查基色与最不利杂质测值 | `GET /api/grading/{source}` | `app/modules/m3_grading/service.py` | `tests/test_grading.py` |
| M4 干重折算 | 核对逐批湿、干、水重 | `GET /api/drymass/{source}` | `app/modules/m4_drymass/fold.py` | `tests/test_drymass.py` |
| M5 目标配载 | 看每车分装片段、预算与欠装 | `GET /api/loading/{source}` | `app/modules/m5_loading/allocator.py` | `tests/test_loading.py` |
| M6 装车对账 | 检查湿干双账与分装连续性 | `GET /api/reconcile/{source}` | `app/modules/m6_reconcile/verify_load.py` | `tests/test_reconcile.py` |
| M7 签单凭证 | 签单、重跑与导出证据 | `POST /api/runs` | `app/modules/m7_archive/signoff.py` `app/modules/m7_archive/service.py` | `tests/test_archive.py` `tests/test_bundle.py` |
| M8 批次接收 | 回传到货、查暂定可装与正式余料、发布切换 | `POST /api/batches/{batch}/intakes` `GET /api/batches/{batch}/ledger` `POST /api/batches/{batch}/publish` | `app/modules/m8_intake/service.py` `app/modules/m8_intake/merge.py` | `tests/test_intake.py` |

## 接收裁决

部分到货按批料放行：到货磅单采信、含水上下层齐、分级证据齐，三者同时满足的批料，其折干量记为暂定可装量，可用于配载；缺任一项，到货湿重挂待化验，不得配载，更不得当作已消费。
末班回传封批（`closed`）且全部到货批料化验齐、无未决隔离、湿干账对平时，批次齐全；只有齐全批次的余料才能发布为正式余料，此前一律为暂定余料。
回传按批次与内容摘要幂等，重复回传不新增接收量；跨回传的相同行按内容归并一次，后到来源逐批留痕。发布切换失败时保留上一已发布快照；后到证据只改当前台账，发布状态不变，直到下一次发布成功。

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 处理 | 位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-06 | 重量带千分位及全角数字 | 数值解析失败 | 先归一到数值再转克 | `app/modules/m1_weighing/mass.py` | `tests/test_weighing.py::test_thousands_and_subgram` |
| TRAP-07 | 下层含水以 N/A 回传 | 当作零水重 | 留下缺样并记待折干湿重 | `app/modules/m2_moisture/service.py` | `tests/test_moisture.py::test_missing_position_is_not_zero` |
| TRAP-08 | 磅单前导零 | 数字化损失 | 单号保持字符 | `app/modules/m1_weighing/service.py` | `tests/test_weighing.py::test_zero_net_isolated_and_identifier_kept` |
| TRAP-10 | 代表样加权保留小数 | 提前截断比率 | 只在最终水重按克舍入 | `app/modules/m4_drymass/fold.py` | `tests/test_drymass.py::test_fraction_precision_carried_to_final_gram` |
| TRAP-14 | 同编号重量不同 | 后写覆盖 | 同号全部隔离 | `app/modules/m1_weighing/service.py` | `tests/test_weighing.py::test_conflicting_ticket_rejects_both_not_just_later` |
| TRAP-15 | 含水混用小数、百分比与 ppm | 倍率错用 | 按单位归一 | `app/modules/m2_moisture/ratio.py` | `tests/test_moisture.py::test_mixed_unit_converted_same_ratio` |
| TRAP-19 | 同批多个杂质测值 | 最后值覆盖或平均 | 按最不利值控制 | `app/modules/m3_grading/service.py` | `tests/test_grading.py::test_worst_case_impurity_across_valid_samples` |
| TRAP-22 | 白、透明等颜色别名 | 资格错判 | 固定归一色类 | `app/modules/m3_grading/classes.py` | `tests/test_grading.py::test_aliases_normalize_transparent_to_white` |
| TRAP-23 | 同批分给两车 | 重复占用交界 | 连续左闭右开 | `app/modules/m5_loading/allocator.py` | `tests/test_loading.py::test_one_lot_contiguous_across_vehicles` |
| TRAP-24 | 杂质预算剩半克 | 多配一克超限 | 整除取下界并核账 | `app/modules/m5_loading/allocator.py` | `tests/test_loading.py::test_budget_limits_exact_last_gram` |
| TRAP-25 | 同一回传重复提交 | 接收量翻倍 | 按批次与内容摘要幂等归并 | `app/store.py` | `tests/test_intake.py::test_repeat_intake_adds_no_receiving` |
| TRAP-26 | 回传间磅单重叠 | 合并后重复采信 | 相同行按内容归并一次 | `app/modules/m8_intake/merge.py` | `tests/test_intake.py::test_overlapping_tickets_merged_once` |
| TRAP-27 | 未齐全时发布切换 | 正式余料被覆盖 | 拒绝切换并保留上一发布 | `app/modules/m8_intake/service.py` | `tests/test_intake.py::test_failed_publish_keeps_previous_publication` |
| TRAP-28 | 未到货先排车 | 在途量被当已消费 | 配载只取已到货且化验齐的折干量 | `app/modules/m8_intake/service.py` | `tests/test_intake.py::test_unarrived_never_consumed` |

## 对账

脏样例的 6930 千克有效湿重折为 6444.900 千克干重和 485.100 千克水重。装载 3797.050 千克，余料 2647.850 千克。另有 1080 千克待折干湿重。
