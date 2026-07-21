局域网 WCS 接收端（机器人侧被调服务）
========================================

对方（WCS / 联调端）在同一局域网向本机发请求；本服务回固定成功 JSON。

对应接口:
  POST /adaptor/api/wcs/sendcasetask    拼箱物料信息下发
  POST /adaptor/api/wcs/boxarrive       物料到达
  POST /adaptor/api/wcs/palletarrive    托盘到达（新增）
  GET  /api/status                      系统状态（注意：无 /adaptor 前缀）

我方向对方下传（不在本服务，写在 packing_config.yaml）:
  POST /api/wcs/sendpalletplanresult    接口2 规划结果（注意：/api/wcs/...）

安装:
  pip install -r requirements.txt

启动:
  python run_receiver.py
  （或随 realtime_dashboard_v3_clean.py 自动启动）

配置:
  config/receiver_config.yaml

本机对外（当前配置）:
  根地址:  http://192.168.0.8:8093
  Swagger: http://192.168.0.8:8093/swagger/index.html

注意:
  - host 必须为 0.0.0.0
  - Windows 防火墙放行 8093 入站
