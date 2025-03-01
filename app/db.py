# SPDX-License-Identifier: LGPL-2.1-or-later


from typing import Any, AsyncGenerator

from sqlalchemy.pool import AsyncAdaptedQueuePool

from contextlib import asynccontextmanager
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession


try:
    from sqlalchemy.ext.asyncio import async_sessionmaker
except ImportError:
    from sqlalchemy.orm import sessionmaker as async_sessionmaker



connection_string = f"postgresql+psycopg://{os.environ['DB_USER']}:{os.environ['DB_PASS']}@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"

engine = create_async_engine(
    connection_string,
    poolclass=AsyncAdaptedQueuePool,
    pool_pre_ping=True,
    max_overflow=80
)
session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession | Any, Any]:
    async with session_maker() as session:
        try:
            async with session.begin():
                yield session
                await session.commit()
        except:
            await session.rollback()
            raise
        finally:
            await session.close()
