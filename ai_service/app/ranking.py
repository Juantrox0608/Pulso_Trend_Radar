from .schemas import RankingItem, Video


def calculate_ranking(videos: list[Video]) -> list[RankingItem]:
    ordered = sorted((v for v in videos if v.views is not None), key=lambda v: (-v.views, v.id))
    result = []
    position = 0
    previous = None
    for index, video in enumerate(ordered, start=1):
        if video.views != previous:
            position = index
        result.append(RankingItem(video_id=video.id, position=position, value=video.views))
        previous = video.views
    return result
