# encoding:utf-8
import logging

import requests

from bot.bot import Bot
from bot.coze.coze_session import CozeSession
from bot.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config


# coze 对话模型API (可用)
class CozeBot(Bot):
    def __init__(self):
        super().__init__()
        # set the default api_key
        self.api_key = conf().get("coze_key")
        self.bot_id = conf().get("coze_bot_id")
        self.user = conf().get("coze_user")
        self.api_base = conf().get("coze_api_base")

        self.sessions = SessionManager(CozeSession)
        self.args = {
            "model": conf().get("model") or "gpt-3.5-turbo",  # 对话模型的名称
            "temperature": conf().get("temperature", 0.9),  # 值在[0,1]之间，越大表示回复越具有不确定性
            # "max_tokens":4096,  # 回复最大的字符数
            "top_p": conf().get("top_p", 1),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "request_timeout": conf().get("request_timeout", None),  # 请求超时时间，openai接口默认设置为600，对于难问题一般需要较长时间
            "timeout": conf().get("request_timeout", None),  # 重试超时时间，在这个时间内，将会自动重试
        }

    def reply(self, query, context=None):
        # acquire reply content
        if context.type == ContextType.TEXT:
            logger.info("[COZE] query={}".format(query))

            session_id = context["session_id"]
            reply = None
            clear_memory_commands = conf().get("clear_memory_commands", ["#清除记忆"])
            if query in clear_memory_commands:
                self.sessions.clear_session(session_id)
                reply = Reply(ReplyType.INFO, "记忆已清除")
            elif query == "#清除所有":
                self.sessions.clear_all_session()
                reply = Reply(ReplyType.INFO, "所有人记忆已清除")
            elif query == "#更新配置":
                load_config()
                reply = Reply(ReplyType.INFO, "配置已更新")
            if reply:
                return reply
            logger.info("[COZE] session query={}".format(query))

            new_args = None
            # if context.get('stream'):
            #     # reply in stream
            #     return self.reply_text_stream(query, new_query, session_id)

            reply_content = self.reply_text(session_id, query, args=new_args)
            logger.info(
                "[COZE] new_query={}, session_id={}, reply_content={}".format(
                    query,
                    session_id,
                    reply_content,
                )
            )
            if reply_content["result"]:
                logger.info(
                    "success={}".format(
                        reply_content,
                    )
                )
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            else:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
                logger.debug("[COZE] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def sync_chat(self, conversation_id, query):
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'Host': 'api.coze.com',
            'Connection': 'keep-alive'
        }
        data = {
            "conversation_id": conversation_id,
            "bot_id": self.bot_id,
            "user": self.user,
            "query": query,
            "stream": False
        }

        response = requests.post(self.api_base, headers=headers, json=data)
        logger.info("query ok and get response={}".format(response))
        return response.json()

    def parse_response(self, response):
        if response['code'] == 0:
            conversation_id = response['conversation_id']
            content = next((message['content'] for message in response['messages'] if message['type'] == 'answer'),
                           None)
            return {
                'result': True,
                'content': content,
                'conversation_id': conversation_id
            }
        else:
            print("Request failed")
            return {
                'result': False,
                'message': response.get('msg', 'Unknown error')
            }


    def reply_text(self, session_id, query, args=None, retry_count=0) -> dict:
        """
        call openai's ChatCompletion to get the answer
        :param session: a conversation session
        :param session_id: session id
        :param retry_count: retry count
        :return: {}
        """
        try:
            response = self.sync_chat(session_id, query)
            return self.parse_response(response)
        except Exception as e:
            logger.warn("[COZE] exception: {}".format(e))
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

            if need_retry:
                logger.warn("[COZE] 第{}次重试".format(retry_count + 1))
                return self.reply_text(session_id, query, args, retry_count + 1)
            else:
                return result
