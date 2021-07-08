import asyncio, re, traceback
from collections import OrderedDict
from typing      import Dict, List, Optional, Set, Tuple

from irctokens import build, Line
from ircrobots import Bot as BaseBot
from ircrobots import Server as BaseServer

from ircchallenge import Challenge
from ircstates.numerics import *
from ircrobots.matching import (Response, Folded, Formatless, Regex, Nick,
    ANY, SELF)
from ircrobots.formatting import strip as format_strip

from .config import Config

RE_NSACCOUNTNAME = re.compile(r"^NickServ (?P<old1>\S+)(?: .(?P<old2>\S+).)? SET:ACCOUNTNAME: (?P<new>\S+)$")
RE_PSCONTACTADD  = re.compile(r"^ProjectServ \S+ PROJECT:CONTACT:ADD: (?P<gc>\S+) ")
RE_PSCONTACTDEL  = re.compile(r"^ProjectServ \S+ PROJECT:CONTACT:DEL: (?P<gc>\S+) ")

# not in ircstates yet...
RPL_RSACHALLENGE2      = "740"
RPL_ENDOFRSACHALLENGE2 = "741"
RPL_YOUREOPER          = "381"

class Server(BaseServer):
    group_contacts:   Dict[str, int] = {}
    banchan_accounts: Dict[str, str] = {}
    banchan_counts:   Dict[str, int] = {}

    def __init__(self,
            bot:      BaseBot,
            name:     str,
            config:   Config):

        super().__init__(bot, name)
        self._config   = config

    def set_throttle(self, rate: int, time: float):
        # turn off throttling
        pass


    async def _get_group_contacts(self
            ) -> Dict[str, int]:
        await self.send(build("PRIVMSG", ["ProjectServ", "LIST *"]))

        ps = Nick("ProjectServ")
        ps_list_line = Response(
            "NOTICE", [SELF, Formatless(Regex(r"^- "))], source=ps
        )
        ps_list_end  = Response(
            "NOTICE", [SELF, Formatless(Regex(r"^\d+ matches "))], source=ps
        )

        gcs: Dict[str, int] = {}
        while True:
            line = await self.wait_for({
                ps_list_line, ps_list_end
            })
            text = self.casefold(format_strip(line.params[1]))

            if text.startswith("- "):
                pgcs = text.split("; ", 1)[1][:-1].split(", ")
                for gc in pgcs:
                    if gc == "no contacts":
                        continue
                    elif not gc in gcs:
                        gcs[gc] = 1
                    else:
                        gcs[gc] += 1
            else:
                break
        return gcs

    def _get_account_bans(self
            ) -> Dict[str, str]:

        accounts: Dict[str, str] = {}
        bc_prefix = self.casefold(self._config.banchan_prefix)
        for chan_name in self.channels.keys():
            if chan_name.startswith(bc_prefix):
                chan = self.channels[chan_name]
                for ban in chan.list_modes["b"]:
                    if ban.startswith("$a:"):
                        account = self.casefold(ban.split(":", 1)[1])
                        accounts[account] = chan_name
        return accounts

    async def _init_invex(self):
        # dict of {account: project_count}
        ps_accounts   = await self._get_group_contacts()
        ps_accounts_s = set(ps_accounts.keys())
        # dict of {account: ban_channel}
        bc_accounts   = self._get_account_bans()
        bc_accounts_s = set(bc_accounts.keys())

        # get all our ban channels
        channel_sort: List[Tuple[str, int]] = []
        bc_prefix = self.casefold(self._config.banchan_prefix)
        for chan_name in sorted(self.channels.keys()):
            if chan_name.startswith(bc_prefix):
                ban_count = len(self.channels[chan_name].list_modes["b"])
                channel_sort.append((chan_name, ban_count))
        # sort by who's got the most bans set
        channel_sort.sort(reverse=True, key=lambda c: c[1])
        # make it an (ordered) dictionary
        channels: Dict[str, int] = OrderedDict(channel_sort)

        # iter account bans we have that belong to non-GCs
        for remove_account in bc_accounts_s-ps_accounts_s:
            # get chan and remove from bc_accounts
            chan = bc_accounts.pop(remove_account)
            mask = f"$a:{remove_account}"
            # remove ban
            await self.send(build("MODE", [chan, "-b", mask]))

            # update channel ban count
            channels[chan] -= 1
            # add new bans to this channel first
            channels.move_to_end(chan, last=True)

        # values might have changed
        channel_sort = list(channels.items())
        channel_sort.sort(reverse=True, key=lambda c: c[1])
        channels = OrderedDict(channel_sort)

        # get rid of channels still at max ban count
        for chan, count in list(channels.items()):
            if count >= self._config.banchan_max:
                # we're always looking at the first item
                # either we popped everything before this or this is the
                # first loop
                channels.move_to_end(chan, last=True)
            else:
                break

        # iter group contacts that have no account bans
        for add_account in ps_accounts_s-bc_accounts_s:
            chan = list(channels.keys())[0]
            bc_accounts[chan] = add_account
            mask = f"$a:{add_account}"
            await self.send(build("MODE", [chan, "+b", mask]))

            channels[chan] += 1
            bc_accounts[add_account] = chan
            # don't add more bans to this channel if its bans are full
            if channels[chan] >= self._config.banchan_max:
                channels.move_to_end(chan, last=True)

        self.group_contacts   = ps_accounts
        self.banchan_accounts = bc_accounts
        self.banchan_counts   = channels

    async def _oper_up(self,
            oper_name: str,
            oper_file: str,
            oper_pass: str):

        try:
            challenge = Challenge(keyfile=oper_file, password=oper_pass)
        except Exception:
            traceback.print_exc()
        else:
            await self.send(build("CHALLENGE", [oper_name]))
            challenge_text = Response(RPL_RSACHALLENGE2,      [SELF, ANY])
            challenge_stop = Response(RPL_ENDOFRSACHALLENGE2, [SELF])
            #:lithium.libera.chat 740 sandcat :foobarbazmeow
            #:lithium.libera.chat 741 sandcat :End of CHALLENGE

            while True:
                challenge_line = await self.wait_for({
                    challenge_text, challenge_stop
                })
                if challenge_line.command == RPL_RSACHALLENGE2:
                    challenge.push(challenge_line.params[1])
                else:
                    retort = challenge.finalise()
                    await self.send(build("CHALLENGE", [f"+{retort}"]))
                    break

    async def line_read(self, line: Line):
        if line.command == RPL_WELCOME:
            await self.send(build("MODE", [self.nickname, "+g"]))
            oper_name, oper_file, oper_pass = self._config.oper
            await self._oper_up(oper_name, oper_file, oper_pass)

        elif line.command == RPL_YOUREOPER:
            pass

        elif line.command == RPL_ENDOFBANLIST:
            chan_name = self.casefold(line.params[1])
            bc_prefix = self.casefold(self._config.banchan_prefix)
            if chan_name.startswith(bc_prefix):
                self.banchan_counts[chan_name] = 0
                if len(self.banchan_counts) == self._config.banchan_count:
                    # we've got ban lists for all our ban channels
                    await self._init_invex()

        elif (line.command == "PRIVMSG" and
                self.is_channel(line.params[0]) and
                not self.is_me(line.hostmask.nickname)):

            reference = f"{line.hostmask.nickname} {line.params[1]}"
            reference = format_strip(reference)

            m_nsaccountname = RE_NSACCOUNTNAME.search(reference)
            m_pscontactadd  = RE_PSCONTACTADD.search(reference)
            m_pscontactdel  = RE_PSCONTACTDEL.search(reference)

            if m_nsaccountname is not None:
                old1 = m_nsaccountname.group("old1")
                old2 = m_nsaccountname.group("old2")
                old  = self.casefold(old2 or old1)
                new  = self.casefold(m_nsaccountname.group("new"))

                if old in self.banchan_accounts:
                    chan = self.banchan_accounts.pop(old)
                    self.banchan_accounts[new] = chan
                    await self.send(build(
                        "MODE", [chan, "-b+b", f"$a:{old}", f"$a:{new}"]
                    ))

            elif m_pscontactadd is not None:
                gc = self.casefold(m_pscontactadd.group("gc"))
                if not gc in self.group_contacts:
                    self.group_contacts[gc] = 1
                    chan = list(self.banchan_counts)[0]
                    await self.send(build("MODE", [chan, "+b", f"$a:{gc}"]))

                    self.banchan_counts[chan] += 1
                    self.banchan_accounts[gc] = chan
                    if self.banchan_counts[chan] >= self._config.banchan_max:
                        self.banchan_counts.move_to_end(chan, last=True)
                else:
                    self.group_contacts[gc] += 1

            elif m_pscontactdel is not None:
                gc   = self.casefold(m_pscontactdel.group("gc"))
                chan = self.banchan_accounts[gc]

                self.group_contacts[gc] -= 1
                if not self.group_contacts[gc]:
                    await self.send(build("MODE", [chan, "-b", f"$a:{gc}"]))
                    del self.group_contacts[gc]
                    del self.banchan_accounts[gc]
                    self.banchan_counts[chan] -= 1
                    self.banchan_counts.move_to_end(chan, last=False)

    def line_preread(self, line: Line):
        print(f"< {line.format()}")
    def line_presend(self, line: Line):
        print(f"> {line.format()}")

class Bot(BaseBot):
    def __init__(self, config: Config):
        super().__init__()
        self._config = config

    def create_server(self, name: str):
        return Server(self, name, self._config)
