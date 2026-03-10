for i in $(seq 1 100); do
  python3 run_client.py | tee -a logs/client.log
done
