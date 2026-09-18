# SeatBond

影院连座锁座：按场次厅图查找连续空座，过道列断开，冲突检测既有持座。

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4100 |
| API | http://localhost:9100 |
| API 文档 | http://localhost:9100/docs |
| Postgres | localhost:5442 |

健康检查：`GET http://localhost:9100/api/health`

## 页面

- `/halls` — 影厅 · 厅图版本（版本号、冻结提示、编辑与复制新版本）
- `/showtimes` — 场次
- `/seatmap` — 座位图（大网格热力）
- `/hold` — 锁座
- `/orders` — 订单
- `/conflicts` — 冲突

## 使用说明

1. 在影厅与场次页确认厅图与排期。
2. 打开座位图查看占用热力，在锁座页输入连座人数并提交。
3. 订单页查看持座结果；冲突页查看重叠请求。

## 厅图版本冻结

影厅的行列数与过道列不原地改写历史：每次变更生成新版本号，场次创建时绑定某一厅图版本。
若某版本已被场次引用且该场次仍存在持有中持座，该版本**冻结**——禁止再改其 `aisle_cols` 与行列，
只能「复制为新版本」供后续场次选用；旧场次的座位图与历史持座坐标永远按旧版本渲染。

| 接口 | 说明 |
| --- | --- |
| `GET /api/halls/{hall_id}/versions` | 版本列表（含 `frozen` 冻结状态、引用场次数） |
| `PUT /api/versions/{version_id}` | 修改版本行列/过道；冻结版本返回 409 可读提示 |
| `POST /api/halls/{hall_id}/versions` | 复制为新版本（可带新行列/过道覆盖源版本） |
| `POST /api/showtimes` | 创建场次并绑定版本（默认绑该厅最新版本） |
| `POST /api/showtimes/{id}/layout_version` | 场次换绑版本；存在持有中持座时拒绝 |

演示路径（种子数据已内置）：场次已有持座 → 影厅页编辑 v1 过道保存被拒（409 提示）→
「复制为新版本」得到 v2 → 新场次绑 v2 使用新过道 → 旧场次座位图仍按 v1 渲染，旧持座坐标不变。

## 开发与测试

```bash
docker compose exec api pytest -q
```
