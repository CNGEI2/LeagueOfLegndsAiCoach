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
