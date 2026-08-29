import redis

try:
    r = redis.Redis(host='localhost', port=6379, db=0)
    r.flushall()
    print("Redis flushed successfully.")
except Exception as e:
    print(f"Error flushing redis: {e}")
