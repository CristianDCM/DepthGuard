"""Modelos Pydantic para request/response."""

from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    usuario: str
    password: str


class RegistroRequest(BaseModel):
    nombre: str


class HistorialResponse(BaseModel):
    historial: list


class UsuariosResponse(BaseModel):
    usuarios: list
