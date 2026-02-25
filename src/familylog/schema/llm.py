from pydantic import BaseModel, Field


class PhotoOutput(BaseModel):
    caption: str = Field(..., description='Заголовок обрабатываемого изображения')
    description: str = Field(..., description='Описание обрабатываемого изображения')