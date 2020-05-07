from db import db
from utils import extract_remainder_after_fragments
from game import lookup_game_by_name_or_alias, games
from dotenv import load_dotenv
import os

load_dotenv()

CLIENT_ID = os.getenv('CLIENT_ID')


def create_mention(player):
    return '<@!%s>' % player.id


def get_any_ready_messages(game):
    if game.is_ready_to_play:
        return game.get_ready_messages()
    return []


def split_by_first_mention(message):
    msg = message.content
    if msg.startswith('<@'):
        idx = msg.index('>') + 1
        return msg[:idx], msg[idx:].strip()
    else:
        return '', msg


def is_bot_mention(mention):
    return mention[3 if mention.startswith('<@!') else 2:-1] == CLIENT_ID


class GameExtractionMixin:
    multi_game_delimiter = '/'

    def get_all_responses_without_game(self, message):
        return []

    def get_all_responses(self, message):
        plays = extract_remainder_after_fragments(self.fragments, message.content)
        responses = []
        game_names = plays.split(self.multi_game_delimiter)
        if any(game_names):
            for game_name in game_names:
                if game_name:
                    game = lookup_game_by_name_or_alias(game_name)
                    responses += self.get_all_responses_with_game(message, game)
        else:
            responses += self.get_all_responses_without_game(message)
        return responses


class MessageHandler:
    def should_handle(self, message):
        raise NotImplementedError()

    def get_all_responses(self, message):
        raise NotImplementedError()


class ContentBasedHandler(MessageHandler):
    fragments = []

    def should_handle(self, message):
        return any(message.content.lower().startswith(f.lower()) for f in self.fragments)


class MentionMessageHandler(MessageHandler):
    keywords = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fragments = self.keywords

    def should_handle(self, message):
        mention, remainder = split_by_first_mention(message)
        return is_bot_mention(mention) and any(remainder.lower().startswith(kw.lower()) for kw in self.keywords)

    def split_string_by_keywords(self, string):
        for keyword in self.keywords:
            kw_removed_string = string.replace(keyword, '', 1)

            if kw_removed_string != string:
                kw_removed_string = kw_removed_string.strip()
                return keyword, kw_removed_string

        return None, string


class WouldPlayHandler(GameExtractionMixin, ContentBasedHandler):
    fragments = ["I'd play", "id play", "I'd paly", "id paly", "I’d play", "I’d paly", "I’dplay", "I’dpaly"]

    def get_all_responses_with_game(self, message, game):
        would_play = db.record_would_play(message.author, game)
        return ["%s would play %s (that's %s)" % (would_play.user, game, len(game.get_available_players()))] + get_any_ready_messages(game)


class SameHandler(GameExtractionMixin, ContentBasedHandler):
    fragments = ['same to', 'same']

    def get_all_responses_without_game(self, message):
        last_would_plays = db.get_last_would_plays_at_same_time()

        if not last_would_plays:
            return []

        messages = []
        games = set([lwp.game for lwp in last_would_plays])

        for game in games:
            would_play = db.record_would_play(message.author, game)
            messages += ["%s would also play %s (that's %s)" % (would_play.user, game, len(game.get_available_players()))]
        for game in games:
            messages += get_any_ready_messages(game)
        return messages

    def get_all_responses_with_game(self, message, game):
        return self.get_all_responses_with_optional_game(message, game)

    def get_all_responses_with_optional_game(self, message, game):
        last_would_play = db.get_last_would_play(game)

        if not last_would_play:
            return []

        game = game or last_would_play.game
        would_play = db.record_would_play(message.author, game)

        return ["%s would also play %s (that's %s)" % (would_play.user, game, len(game.get_available_players()))] + get_any_ready_messages(game)


class StatusHandler(MentionMessageHandler):
    keywords = ['status']

    def get_all_responses(self, message):
        messages = ['Bot alive']
        ready_messages = []
        for game in games:
            players = game.get_available_players()
            if players:
                messages.append('%s has %s' % (game, len(players)))
                ready_messages += get_any_ready_messages(game)
        return ['\n'.join(messages + ready_messages)]


class ClearHandler(GameExtractionMixin, MentionMessageHandler):
    keywords = ['clear']

    def get_all_responses_with_game(self, message, game):
        if game:
            db.clear_game(game)
            return ['Cleared %s' % game]
        else:
            return ['No game specified!']


class CancelHandler(MentionMessageHandler):
    keywords = ['cancel']

    def get_all_responses(self, message):
        db.cancel_would_plays(message.author)
        return ['Cancelled all play requests from %s' % (message.author.display_name)]


class PingHandler(GameExtractionMixin, MentionMessageHandler):
    keywords = ['ping', 'p']

    def get_all_responses_with_game(self, message, game):
        players = game.get_players_for_next_game()
        db.clear_game(game)
        return ['%s - ready to play %s.' % (','.join([create_mention(p) for p in players]), game)]


class AccidentalRoleMentionHandler(MessageHandler):
    def should_handle(self, message):
        return 'Play Register' in message.clean_content and '<@&' in message.content

    def get_all_responses(self, message):
        return ['It looks like you tried to @ me but might have accidentally selected the role instead']


class QueryGameHandler(MentionMessageHandler):
    keywords = ['query games']

    def get_all_responses(self, message):
        return ['\n'.join([game.name for game in games])]


class QueryPropertyHandler(MentionMessageHandler):
    keywords = ['query']

    def get_all_responses(self, message):
        mention, remainder = split_by_first_mention(message)
        found_keyword, remainder = self.split_string_by_keywords(remainder)
        attribute, game_name = remainder.split(' ')[:2]
        game = lookup_game_by_name_or_alias(game_name)
        attribute_display = {
            'aliases': lambda z: ', '.join([alias for alias in z])
        }
        display_function = attribute_display.get(attribute, lambda x: str(x))
        return ["%s: %s" % (attribute, display_function(getattr(game, attribute)))]
