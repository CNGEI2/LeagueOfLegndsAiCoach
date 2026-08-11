import copy

MATCH_PAYLOAD: dict[str, object] = {
    "metadata": {
        "matchId": "NA1_123456789",
        "participants": [f"puuid-{index}" for index in range(1, 11)],
    },
    "info": {
        "gameCreation": 1720000000000,
        "gameDuration": 1800,
        "gameVersion": "16.15.602.1234",
        "queueId": 420,
        "participants": [
            {
                "puuid": f"puuid-{index}",
                "teamId": 100 if index <= 5 else 200,
                "championId": 102 + index,
                "win": index <= 5,
                "teamPosition": (
                    ("MIDDLE", "JUNGLE", "TOP", "BOTTOM", "UTILITY")[index - 1]
                    if index <= 5
                    else ""
                ),
                "kills": index,
                "deaths": index - 1,
                "assists": index + 2,
                "goldEarned": 12000 + index,
                "totalDamageDealtToChampions": 15000 + index,
                "visionScore": 10 + index,
                "totalMinionsKilled": 200 + index,
                "neutralMinionsKilled": 13,
                "item0": 1055 if index == 1 else 0,
                "item1": 6672 if index == 1 else None,
                "item2": 3006 if index == 1 else None,
                "unexpectedField": "ignored",
            }
            for index in range(1, 11)
        ],
    },
}


def _synthetic_participant_frame(participant_id: int) -> dict[str, object]:
    return {
        "participantId": participant_id,
        "level": participant_id,
        "currentGold": 100 * participant_id,
        "totalGold": 1000 * participant_id,
        "minionsKilled": 10 * participant_id,
        "jungleMinionsKilled": participant_id,
        "xp": 200 * participant_id,
        "position": {"x": 100 * participant_id, "y": 200 * participant_id},
        "unexpectedFrameField": "ignored",
    }


TIMELINE_PAYLOAD: dict[str, object] = {
    "metadata": {
        "matchId": "NA1_fixture_timeline",
        "participants": [f"fixture-puuid-{index}" for index in range(1, 11)],
        "unexpectedMetadataField": "ignored",
    },
    "info": {
        "frameInterval": 60_000,
        "frames": [
            {
                "timestamp": 0,
                "participantFrames": {
                    str(index): _synthetic_participant_frame(index) for index in range(1, 11)
                },
                "events": [
                    {
                        "type": "ITEM_PURCHASED",
                        "timestamp": 1_000,
                        "participantId": 1,
                        "itemId": 1055,
                    },
                    {
                        "type": "UNKNOWN_EVENT_TYPE",
                        "timestamp": 1_500,
                        "arbitrary": True,
                    },
                ],
                "unexpectedFrameContainerField": "ignored",
            },
            {
                "timestamp": 60_000,
                "participantFrames": {
                    str(index): _synthetic_participant_frame(index) for index in range(1, 11)
                },
                "events": [
                    {
                        "type": "CHAMPION_KILL",
                        "timestamp": 61_000,
                        "killerId": 1,
                        "victimId": 6,
                        "assistingParticipantIds": [2, 3],
                        "position": {"x": 4000, "y": 5000},
                    },
                    {
                        "type": "ELITE_MONSTER_KILL",
                        "timestamp": 62_000,
                        "killerId": 2,
                        "killerTeamId": 100,
                        "monsterType": "DRAGON",
                        "monsterSubType": "FIRE_DRAGON",
                        "position": {"x": 9800, "y": 4400},
                    },
                    {
                        "type": "BUILDING_KILL",
                        "timestamp": 63_000,
                        "killerId": 3,
                        "teamId": 200,
                        "buildingType": "TOWER_BUILDING",
                        "laneType": "MID_LANE",
                        "towerType": "OUTER_TURRET",
                        "position": {"x": 8955, "y": 8510},
                    },
                    {
                        "type": "ITEM_SOLD",
                        "timestamp": 64_000,
                        "participantId": 4,
                        "itemId": 1001,
                    },
                    {
                        "type": "ITEM_DESTROYED",
                        "timestamp": 65_000,
                        "participantId": 5,
                        "itemId": 2003,
                    },
                    {
                        "type": "ITEM_UNDO",
                        "timestamp": 66_000,
                        "participantId": 1,
                        "beforeId": 1055,
                        "afterId": 0,
                    },
                    {
                        "type": "CHAMPION_KILL",
                        "timestamp": 67_000,
                        "killerId": 0,
                        "victimId": 7,
                        "assistingParticipantIds": [],
                    },
                ],
            },
        ],
        "unexpectedInfoField": "ignored",
    },
    "unexpectedTopLevelField": "ignored",
}


def timeline_payload_for_normalizer(*, match_id: str = "NA1_fixture") -> dict[str, object]:
    """Synthetic Timeline payload with a stable match ID for normalizer contracts."""
    payload = copy.deepcopy(TIMELINE_PAYLOAD)
    payload["metadata"]["matchId"] = match_id
    return payload


def timeline_payload_with_optional_gaps() -> dict[str, object]:
    """Synthetic payload covering missing optional values while preserving zeros."""
    payload = timeline_payload_for_normalizer(match_id="NA1_fixture_optional")
    frames = payload["info"]["frames"]
    assert isinstance(frames, list)
    frame0 = frames[0]
    assert isinstance(frame0, dict)
    participant_frames = frame0["participantFrames"]
    assert isinstance(participant_frames, dict)
    participant_frames["1"] = {
        "participantId": 1,
        "level": 0,
        "currentGold": 0,
        "totalGold": 0,
        "minionsKilled": 0,
        "jungleMinionsKilled": 0,
        "xp": 0,
    }
    frames[1] = {
        "timestamp": 60_000,
        "participantFrames": {
            str(index): _synthetic_participant_frame(index) for index in range(1, 11)
        },
        "events": [
            {
                "type": "CHAMPION_KILL",
                "timestamp": 61_000,
                "killerId": 1,
                "victimId": 6,
                "assistingParticipantIds": [2],
            },
            {
                "type": "ELITE_MONSTER_KILL",
                "timestamp": 62_000,
                "killerId": 2,
                "killerTeamId": 100,
                "monsterType": "BARON_NASHOR",
            },
            {
                "type": "BUILDING_KILL",
                "timestamp": 63_000,
                "killerId": 3,
                "teamId": 200,
                "buildingType": "TOWER_BUILDING",
            },
            {
                "type": "ITEM_UNDO",
                "timestamp": 66_000,
                "participantId": 1,
                "beforeId": 0,
                "afterId": 0,
            },
        ],
    }
    return payload
