from bson import ObjectId
from fastapi import FastAPI, Body, HTTPException, Depends, WebSocket, WebSocketDisconnect, Header
from pydantic import BaseModel, Field, BeforeValidator
from typing import List, Optional, Annotated
from datetime import datetime, timedelta
from fastapi_login import LoginManager
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import pytz

kst = pytz.timezone('Asia/Seoul')

MONGO_DETAILS = "mongodb+srv://sco3o17:pw@cluster0.al5hilk.mongodb.net/"

client = AsyncIOMotorClient(MONGO_DETAILS)

db = client.imadyou

userCollection = db.get_collection("user")
projectCollection = db.get_collection("project")
statusCollection = db.get_collection("status")
chatCollection = db.get_collection("chat")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처를 허용하려면 ["*"]로 설정
    allow_credentials=True,
    allow_methods=["*"],  # 모든 메서드를 허용
    allow_headers=["*"],  # 모든 헤더를 허용
)

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
    created_at: str = datetime.now(kst).strftime("%Y.%m.%d")


class UpdateStatus(BaseModel):
    start_date: Optional[str]
    end_date: str = ""
    content: str


class Project(BaseModel):
    id: Optional[pyObjectId] = Field(alias="_id", default=None)
    week: int
    project_name: str
    thumbnail: str
    url: Optional[str]
    teammates: List[int]
    introduction: str


class User(BaseModel):
    id: Optional[pyObjectId] = Field(alias="_id", default=None)
    number: int = Field(..., ge=0, le=21)
    user_name: str = Field(...)
    project_list: List[Project] = []
    status_list: List[Status] = []


class Chat(BaseModel):
    user_name: str
    message: str
    timestamp: str = datetime.now().strftime("%Y.%m.%d")


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
            week2 != '마니또' or
            week3 != '올빼미주막' or
            week4 != '계룡산'):
        return False
    return user


# 현재 로그인된 사용자 반환 함수
async def get_current_user(user=Depends(manager)):
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 안돼있습니다!!!")
    return user


# 로그인 요청
@app.post("/login")
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
@app.post("/how/{number}/add", response_model=Status)
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


# 근황 삭제
@app.delete("/how/{number}/delete/{status_id}", response_model=Status)
async def delete_status(number: int, status_id: str, current_user: User = Depends(get_current_user)):
    if current_user.number != number:
        raise HTTPException(status_code=403, detail="근황 삭제는 본인만 가능합니다!")

    user = await userCollection.find_one({"number": number})
    if not user:
        raise HTTPException(status_code=404, detail=f'{number}번 유저를 찾을 수 없습니다')

    existing_status = await statusCollection.find_one({"_id": ObjectId(status_id)})
    if not existing_status:
        raise HTTPException(status_code=404, detail=f'ObjectID-{status_id}인 근황을 찾을 수 없습니다')

    await statusCollection.delete_one({"_id": ObjectId(status_id)})

    await userCollection.update_one(
        {"number": number},
        {"$pull": {"status_list": {"_id": ObjectId(status_id)}}}
    )

    return existing_status


# -------------------------------------채팅 섹션 시작----------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.chat_history: list[str] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

    async def send_chat_history(self, websocket: WebSocket):
        messages = await chatCollection.find().sort("_id", 1).to_list(length=100)
        for message in messages:
            formatted_message = f"#{message['user_name']}: {message['message']} ({message['timestamp']})"
            await websocket.send_text(formatted_message)


chat_manager = ConnectionManager()


@app.websocket("/chat/{name}")
async def websocket_endpoint(name: str, websocket: WebSocket):
    await chat_manager.connect(websocket)
    await chat_manager.send_chat_history(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            chat_message = {
                "user_name": name,
                "message": data,
                "timestamp": datetime.now(kst).strftime("%Y.%m.%d %H:%M:%S")
            }
            await chatCollection.insert_one(chat_message)
            formatted_message = f"#{name}: {data} ({chat_message['timestamp']})"
            await chat_manager.broadcast(formatted_message)

    except WebSocketDisconnect:
        chat_manager.disconnect(websocket)
        await chat_manager.broadcast(f"{name}님의 연결이 끊겼습니다.")
