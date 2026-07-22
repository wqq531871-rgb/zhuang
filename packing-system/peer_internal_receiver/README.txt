Peer-side receiver for full packing_plan JSON
=============================================

对方电脑运行；我方 POST 整份 packing_plan 到对方。

关键配置（搜 TODO）:
  config/receiver_config.yaml
    host: 0.0.0.0                 # 本机监听，不是 IP
    advertise_base_url: http://192.168.0.202:8094   # 对方真实 IPv4
    port / save_dir / internal_path

我方对齐:
  packing-system/config/packing_config.yaml
    internal_base_url: http://192.168.0.202:8094
    internal_path: /adaptor/api/wcs/internal

完整 URL:
  http://192.168.0.202:8094/adaptor/api/wcs/internal

启动:
  pip install -r requirements.txt
  python run_receiver.py

详见: 给对方的运行说明.txt
