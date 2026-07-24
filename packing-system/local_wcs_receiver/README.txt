局域网 WCS 接收端（机器人侧被调服务）
========================================

对方（WCS / 联调端）在同一局域网向本机发请求；本服务回固定成功 JSON。

对应接口（对标接口文档 4.3～4.7）:
  POST /adaptor/api/wcs/sendcasetask    4.3 拼箱物料信息下发（暂仅回成功，不做业务）
  POST /adaptor/api/wcs/boxarrive       4.4 物料到达（暂仅回成功，不做业务）
  POST /adaptor/api/wcs/palletarrive    4.6 托盘到达（暂仅回成功，不做业务）
  GET  /api/status                      4.7 获取系统信息（注意：无 /adaptor 前缀；最快约 1s/次）

统一成功回复示例:
  {"code": 0, "msg": "success", "data": {}}

我方向对方下传（不在本服务，写在 packing_config.yaml）:
  POST .../reqstockinfo                 4.1 库存信息获取
  POST .../sendpalletplanresult         4.2 规划订单输出（注意现场 path 可能是 /api/wcs/...）
  POST /adaptor/api/wcs/reqpallet       4.5 托盘更新（TODO：发送时机与出站客户端待定）

安装:
  pip install -r requirements.txt

启动:
  python run_receiver.py
  （或随 realtime_dashboard_v3_clean.py 自动启动）

配置:
  config/receiver_config.yaml

本机对外（当前配置）:
  根地址:  见 receiver_config.yaml 的 advertise_base_url
  Swagger: {advertise_base_url}/swagger/index.html

注意:
  - host 必须为 0.0.0.0
  - Windows 防火墙放行配置端口入站
