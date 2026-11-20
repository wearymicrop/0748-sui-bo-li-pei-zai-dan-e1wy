# 碎玻璃配载数据字典

| 输入段 | 字段 | 定义 |
|---|---|---|
| `batch` | 批次编号 | 字符串，保留前导零 |
| `tickets` | `ticket`、`lot`、`gross`、`tare`、`unit` | 单号唯一，重量单位 g、kg、t，最大 100 吨且精确到克，毛重必须大于皮重 |
| `moisture` | `lot`、`sample`、`position`、`mass`、`mass_unit`、`water`、`unit` | 批料内样号唯一，样重为 1 克至 30 千克，上层和下层均须有有效样 |
| `grades` | `lot`、`color`、`offcolor`、`impurity`、`unit` | 基色按白、绿、棕归并，同批有效样须颜色一致。杂质和异色各取最不利值 |
| `targets` | `target`、`colors`、`grades`、`mass`、`unit`、`max_impurity`、`impurity_unit`、`priority` | 车次标识唯一，按优先级由小到大执行，平级按输入顺序 |
| 回传 `batch` | 批次编号 | 可省略，带则须与台账批次一致 |
| 回传各段 | `tickets`、`moisture`、`grades`、`targets` | 定义同上，均可只携带部分行；相同行跨回传只归并一次 |
| 回传 `closed` | 封批标记 | 布尔，末班回传置真，表示吨单已全部送出 |
| 台账批料 | `arrived_wet_g`、`provisional_dry_g`、`pending_wet_g`、`allocated_dry_g`、`remaining_g`、`intakes` | 到货湿重、暂定可装量、待化验湿重、暂定配载、余料与来源回传序号 |
| 台账批次 | `closed`、`complete`、`official_remaining_g`、`published` | 齐全批次的余料才能发布为正式余料；`published.stale` 表示发布后有后到证据 |

比例必须带单位 `%`、`fraction` 或 `ppm`，支持精确到 ppm。样品含水上限 30%。各样按样重加权，按批料先四舍五入计水克数，余量全计干重。
异色不大于 3% 且杂质不大于 1% 为 A，异色不大于 10% 且杂质不大于 3% 为 B，其余为 C。色级缺证的干料留作余料。
每车仅考虑符合色级的批料，按杂质由低到高分配。高于预算的批料可借较纯材料的剩余预算配入，最多到整数克。
装载区间为 `[start_g,end_g)`，对每批按从零开始的连续范围切分。干重与水重均按克保存，界面按千克展示。配载供装车复核，司机及过磅操作由外部系统记录。
空磅单无湿重、空抽样全为待折干、空目标无装车指令。输入为 UTF-8 JSON，可带 BOM。
批次接收按回传累计：批料到货且化验齐后，折干量记暂定可装量并可配载；缺证批料的湿重挂待化验，不得配载。批次封批、化验齐且无未决隔离后齐全，齐全批次的余料经发布才是正式余料。回传按批次与内容摘要幂等，重复回传不新增接收量；发布切换失败保留上一已发布快照。
