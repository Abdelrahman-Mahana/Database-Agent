from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.conversation.models import MessageRequest, ConversationContext
from app.conversation.service import ConversationService

router = APIRouter(prefix="/conversation", tags=["conversation"])

@router.post("/message", response_model=ConversationContext)
@inject
def process_message(
    request: MessageRequest,
    conv_service: ConversationService = Depends(Provide[Container.conversation_service])
):
    try:
        return conv_service.process_message(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{conversation_id}", response_model=ConversationContext)
@inject
def get_conversation(
    conversation_id: str,
    conv_service: ConversationService = Depends(Provide[Container.conversation_service])
):
    try:
        return conv_service.get_conversation(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
def delete_conversation(
    conversation_id: str,
    conv_service: ConversationService = Depends(Provide[Container.conversation_service])
):
    conv_service.delete_conversation(conversation_id)
