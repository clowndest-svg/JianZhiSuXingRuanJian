"""Batch projection for a bounded community page, preserving its input order."""
from app_modules.community import read_images


def project(conn, rows, me, signed_photo):
    if not rows:
        return []
    ids = tuple(int(row['id']) for row in rows)
    authors = tuple(sorted({int(row['user_id']) for row in rows}))
    marks = ','.join('?' for _ in ids)
    author_marks = ','.join('?' for _ in authors)
    profiles = {}
    for row in conn.execute(
        f'SELECT u.id,u.public_id,u.username,u.nickname,p.avatar_url FROM users u '
        f'LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id IN ({author_marks})', authors
    ):
        profiles[int(row['id'])] = {
            'id': int(row['id']), 'public_id': row['public_id'] or '',
            'name': (row['nickname'] or row['username'] or '').strip(),
            'avatar': signed_photo(row['avatar_url']) if row['avatar_url'] else '',
        }
    counts = {int(row[0]): int(row[1]) for row in conn.execute(
        f'SELECT post_id,COUNT(*) FROM post_favorites WHERE post_id IN ({marks}) GROUP BY post_id', ids)}
    liked, favorites, follows = set(), set(), set()
    if me:
        uid = int(me['id'])
        liked = {int(row[0]) for row in conn.execute(
            f'SELECT post_id FROM post_likes WHERE user_id=? AND post_id IN ({marks})', (uid, *ids))}
        favorites = {int(row[0]) for row in conn.execute(
            f'SELECT post_id FROM post_favorites WHERE user_id=? AND post_id IN ({marks})', (uid, *ids))}
        follows = {int(row[0]) for row in conn.execute(
            f'SELECT followee_id FROM follows WHERE follower_id=? AND followee_id IN ({author_marks})', (uid, *authors))}
    cards = []
    for row in rows:
        pid, author = int(row['id']), int(row['user_id'])
        images = [signed_photo('/uploads/' + name, scope='post', ref=pid) for name in read_images(row['images'])]
        cards.append({
            'id': pid, 'title': row['title'] or '', 'body': row['body'],
            'images': images, 'image_thumbs': [url + '&thumb=1' for url in images],
            'author': profiles.get(author), 'region': row['region'] or '',
            'created_at': row['created_at'], 'edited_at': row['edited_at'],
            'like_count': int(row['like_count']), 'comment_count': int(row['comment_count']),
            'liked_by_me': pid in liked, 'favorited_by_me': pid in favorites,
            'favorite_count': counts.get(pid, 0), 'followed_by_me': author in follows,
            'mine': bool(me and author == int(me['id'])),
        })
    return cards
