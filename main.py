from fastapi import FastAPI, Body, HTTPException, Depends
from pydantic import BaseModel, Field, BeforeValidator
from typing import List, Optional, Annotated
from datetime import datetime, timedelta
from fastapi_login import LoginManager
from database import userCollection, projectCollection

import base64


def encode_image_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
    return encoded_string


app = FastAPI()

# -----------------------------모델 섹션 시작------------------------------------------------------------------------------

pyObjectId = Annotated[str, BeforeValidator(str)]


class LoginModel(BaseModel):
    user_name: str
    week1: str
    week2: str
    week3: str
    week4: str


class Status(BaseModel):
    id: Optional[pyObjectId] = Field(alias="_id", default=None)
    start_date: str
    end_date: Optional[str]
    content: str
    user_num: int
    created_at: datetime


class Project(BaseModel):
    id: Optional[pyObjectId] = Field(alias="_id", default=None)
    week: int
    project_name: str
    thumbnail: str  # Base64
    url: Optional[str]
    teammates: List[int]
    introduction: str


class User(BaseModel):
    id: Optional[pyObjectId] = Field(alias="_id", default=None)
    number: int = Field(..., ge=0, le=21)
    user_name: str = Field(...)
    project_list: List[Project] = []
    status_list: List[Status] = []


# -----------------------------인증 섹션 시작------------------------------------------------------------------------------

# 비밀 키 설정
SECRET = "your-secret-key"
# LoginManager 객체 생성
manager = LoginManager(SECRET, token_url="/login")


# 사용자 로더 함수: 사용자 이름을 통해 사용자 객체를 반환
@manager.user_loader()
async def load_user(user_name: str):
    user = await userCollection.find_one({"user_name": user_name})
    if user:
        return User(**user)
    return None


async def authenticate_user(
        user_name: str,
        week1: str,
        week2: str,
        week3: str,
        week4: str):
    user = await load_user(user_name)
    if (not user or
            week1 != '화채' or
            week2 != '2주답' or
            week3 != '3주답' or
            week4 != '4주답'):
        return False
    return user


# 현재 로그인된 사용자 반환 함수
async def get_current_user(user=Depends(manager)):
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


# ---------------------------------라우터 섹션 시작------------------------------------------------------------------------


# 로그인 요청
@app.post("/login/")
async def login(data: LoginModel = Body(...)):
    user = await authenticate_user(data.user_name,
                                   data.week1,
                                   data.week2,
                                   data.week3,
                                   data.week4)
    if not user:
        raise HTTPException(status_code=400, detail="유저 못찾음(!)")

    manager.default_expiry = timedelta(hours=6)
    access_token = manager.create_access_token(data={"sub": user.user_name})
    return {"access_token": access_token, "token_type": "bearer"}



# 갤러리 조회
@app.get("/gallery/{week}", response_model=List[Project])
async def get_week_projects(week: int):
    # projectCollection 디비에서 알맞는 week 필드를 가진 아이템만 가져오기
    projects = await projectCollection.find({"week": week}).to_list(length=None)
    if not projects:
        raise HTTPException(status_code=404, detail=f'{week}에 맞는 프로젝트를 찾지 못함')
    return projects
