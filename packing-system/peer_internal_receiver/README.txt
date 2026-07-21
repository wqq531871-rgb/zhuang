Peer-side receiver for full packing_plan JSON
=============================================

This folder is for the OTHER party (or local mock of them).

They receive POST /adaptor/api/wcs/internal with the full packing_plan JSON
and save it under:

  D:\research_code\xiafa\

Install:
  pip install fastapi uvicorn pyyaml

Run:
  python run_receiver.py

Config (edit TODOs):
  config/receiver_config.yaml
    host / port / save_dir / internal_path

Swagger:
  http://127.0.0.1:8094/swagger/index.html

Packing side (your UI) posts to:
  {data_source.api_base_url}{data_source.internal_path}
  e.g. http://192.168.0.191:8092/adaptor/api/wcs/internal

For local self-test, temporarily set packing_config.yaml:
  api_base_url: http://127.0.0.1:8094
  (or point to the peer LAN IP running this receiver)
