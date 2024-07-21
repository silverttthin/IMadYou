from bson import ObjectId
from fastapi import FastAPI, Body, HTTPException, Depends, WebSocket, WebSocketDisconnect, Header
from pydantic import BaseModel, Field, BeforeValidator
from typing import List, Optional, Annotated
from datetime import datetime, timedelta
from fastapi_login import LoginManager

from database import userCollection, projectCollection, statusCollection

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
    start_date: str  #
    end_date: str = ""  #
    content: str  #
    user_num: Optional[int] = None  #
    created_at: str = datetime.now().strftime("%Y.%m.%d")


class UpdateStatus(BaseModel):
    start_date: Optional[str]
    end_date: str = ""
    content: str


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


class ChatMessage(BaseModel):
    user_name: str
    message: str
    timestamp: datetime = datetime.now()


# -----------------------------인증 섹션 시작------------------------------------------------------------------------------

# 비밀 키 설정
SECRET = "your-secret-key"
# LoginManager 객체 생성
manager = LoginManager(SECRET, token_url="/login")


# 사용자 로더 함수: (인증된거라 가정) 사용자 이름을 통해 사용자 객체를 반환
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
        raise HTTPException(status_code=401, detail="로그인이 안돼있습니다!!!")
    return user


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
        raise HTTPException(status_code=404, detail=f'{week}주차에 맞는 프로젝트를 찾지 못함')
    return projects


# 근황 조회
@app.get("/how/{number}", response_model=List[Status])
async def get_status(number: int):
    user = await userCollection.find_one({"number": number})
    if not user:
        raise HTTPException(status_code=404, detail=f'{number}번 유저 조회 불가')
    return user.get("status_list", [])


# 근황 추가
@app.post("/how/{number}/add/", response_model=Status)
async def add_status(number: int, status: Status = Body(...), current_user: User = Depends(get_current_user)):
    if current_user.number != number:
        raise HTTPException(status_code=403, detail="근황 추가는 본인만 가능합니다!")

    user = await userCollection.find_one({"number": number})
    if not user:
        raise HTTPException(status_code=404, detail=f'{status.user_num}을 가진 유저를 찾을 수 없습니다')

    status.user_num = number
    new_status = await statusCollection.insert_one(status.model_dump(by_alias=True, exclude=["id"]))
    created_status = await statusCollection.find_one({"_id": new_status.inserted_id})

    await userCollection.update_one(
        {"number": status.user_num},
        {"$push": {"status_list": created_status}}
    )

    return created_status


# 근황 수정
@app.put("/how/{number}/update/{status_id}", response_model=Status)
async def update_status(number: int, status_id: str, updated_status: UpdateStatus = Body(...),
                        current_user: User = Depends(get_current_user)):
    if current_user.number != number:
        raise HTTPException(status_code=403, detail="근황 수정은 본인만 가능합니다!")

    user = await userCollection.find_one({"number": number})
    if not user:
        raise HTTPException(status_code=404, detail=f'{number}번 유저를 찾을 수 없습니다')

    existing_status = await statusCollection.find_one({"_id": ObjectId(status_id)})
    if not existing_status:
        raise HTTPException(status_code=404, detail=f'ObjectID-{status_id}인 근황을 찾을 수 없습니다')

    await statusCollection.update_one(
        {"_id": ObjectId(status_id)},
        {"$set": updated_status.model_dump(by_alias=True)}
    )
    updated_status_data = await statusCollection.find_one({"_id": ObjectId(status_id)})

    # 유저의 status_list도 업데이트
    await userCollection.update_one(
        {"number": number, "status_list._id": ObjectId(status_id)},
        {"$set": {"status_list.$": updated_status_data}}
    )

    return updated_status_data


# -------------------------------------채팅 섹션 시작----------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):  # 연결 목록에 내 소켓을 넣는다
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):  # 연결 목록에서 내 소켓을 지운다
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):  # 연결된 모든 소켓에 내 메시지를 보낸다
        for connection in self.active_connections:
            await connection.send_text(message)


chat_manager = ConnectionManager()


@app.websocket('/chat/')
async def websocket_endpoint(websocket: WebSocket, token: str = Header(...)):
    try:
        # 토큰을 사용하여 사용자 인증
        user = await manager.get_current_user(token)
    except Exception as e:
        await websocket.close(code=1008)
        return

    await chat_manager.connect(websocket)
    await chat_manager.broadcast(f"반가워요 {user.user_name}님!")

    try:
        while True:
            data = await websocket.receive_text()
            message = ChatMessage(user_name=user.user_name, message=data)
            await chat_manager.broadcast(f"{message.user_name}: {message.message}")  # 채팅 송출

    except WebSocketDisconnect:
        chat_manager.disconnect(websocket)
        await chat_manager.broadcast(f"{user.user_name}님이 나가셨습니다.")
