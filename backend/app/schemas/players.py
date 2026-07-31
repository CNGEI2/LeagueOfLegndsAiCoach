from app.schemas.domain import DomainModel, PlayerView


class ResolvePlayerResponse(DomainModel):
    player: PlayerView
    request_id: str
