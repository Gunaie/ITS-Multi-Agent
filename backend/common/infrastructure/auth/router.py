from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from .security import create_access_token, verify_password, get_password_hash
from .models import UserRepo
from ..limiter import limiter
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

class UserCreate(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, user_in: UserCreate):
    user = UserRepo.get_user_by_username(user_in.username)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    hashed_password = get_password_hash(user_in.password)
    success = UserRepo.create_user(user_in.username, hashed_password)
    if not success:
        raise HTTPException(status_code=500, detail="User creation failed")
    return {"msg": "User created successfully"}

@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user = UserRepo.get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user['hashed_password']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(subject=user['username'])
    return {"access_token": access_token, "token_type": "bearer"}
