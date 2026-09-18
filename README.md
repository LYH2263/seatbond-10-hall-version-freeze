# SeatBond

影院连座锁座：按场次厅图查找连续空座，过道列断开，冲突检测既有持座。

## 厅图版本冻结

影厅的行列数与过道列以**厅图版本**为单位管理，历史不被原地改写：

- 每次变更生成新版本号（`hall_layout_versions`），影厅表镜像最新版本用于列表展示。
- 场次创建时绑定某一厅图版本（缺省绑本厅最新版本），座图渲染与连座计算一律按绑定版本。
- 某版本已被场次引用且该场次仍存在持有中持座（`status = held`）时，该版本**冻结**：
  禁止再改其行列与过道列（`PUT /api/layout-versions/{id}` 返回 409 与可读提示），
  只能复制为新版本供后续场次选用；历史持座的排列表意保持不变。

### 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/halls` | 影厅列表（含当前版本号与冻结状态） |
| GET | `/api/halls/{id}/layout-versions` | 版本列表（含冻结状态、引用场次数） |
| GET | `/api/layout-versions/{id}` | 单版本详情与冻结状态 |
| POST | `/api/halls/{id}/layout-versions` | 复制/新建版本（缺省以最新版本为底，可覆盖行列与过道） |
| PUT | `/api/layout-versions/{id}` | 原地改版本（冻结时 409 拒绝） |
| POST | `/api/showtimes` | 创建场次并绑定厅图版本（`layout_version_id` 可选） |

老库启动时自动补 `showtimes.layout_version_id` 列并回填：无版本的影厅补 v1，未绑定的场次绑到本厅最新版本。

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

- `/halls` — 影厅（版本列表、冻结提示、编辑/另存新版本）
- `/showtimes` — 场次（绑版本创建）
- `/seatmap` — 座位图（大网格热力，按场次绑定版本渲染）
- `/hold` — 锁座
- `/orders` — 订单
- `/conflicts` — 冲突

## 使用说明

1. 在影厅与场次页确认厅图与排期。
2. 打开座位图查看占用热力，在锁座页输入连座人数并提交。
3. 订单页查看持座结果；冲突页查看重叠请求。

## 开发与测试

```bash
docker compose exec api pytest -q
```
