import redis
from config.settings import settings

class RedisClient:
    _instance = None

    @classmethod
    def get_client(cls, decode_responses=True):
        return redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=decode_responses
        )

redis_client = RedisClient.get_client(decode_responses=True)
binary_redis_client = RedisClient.get_client(decode_responses=False)
