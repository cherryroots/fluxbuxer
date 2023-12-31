import os
import sys
import asyncio
import traceback
import discord
import json
import aiofiles
from tabulate import tabulate
from typing import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))

GUILDS = os.getenv("GUILDS")
GUILDS = GUILDS.split(",") if "," in GUILDS else [GUILDS]
GUILDS = [int(guild) for guild in GUILDS]
OPERATOR_ROLE = os.getenv("OPERATOR_ROLE")
OPERATOR_ID = os.getenv("OPERATOR_ID")


async def string_dict(
    dictionary: dict,
    listed: bool = False,
    table_listed: bool = False,
    bet_listed: bool = False,
    table_bet_listed: bool = False,
    num_columns: int = 1,
    sort: bool = False,
):
    if dictionary == {}:
        return "```\n- **None**\n```"
    if listed:
        string = "\n".join([f"- {k}: **{v}**" for k, v in dictionary.items()])
        return string
    if bet_listed:
        string = ""
        for user, bets in dictionary.items():
            for bet, value in bets.items():
                string += f"- **{user}**: **{bet}** for **{value}** fluxbux\n"
        return string
    if table_listed:
        if len(dictionary) == 1:
            num_columns = 1
        num_columns = max(num_columns, 1)
        if sort:
            dictionary = dict(
                sorted(dictionary.items(), key=lambda item: item[1], reverse=True)
            )
        # make dicts for each row
        dicts = [{} for _ in range(len(dictionary) // num_columns)]
        # fill dicts with the values
        for i, (key, value) in enumerate(dictionary.items()):
            dicts[i % len(dicts)][key] = value

        # Create the table headers
        headers = ["user", "fluxbux"] * num_columns

        # Transpose the dicts to rows
        for i, value in enumerate(dicts):
            dicts[i] = list(dicts[i].items())

        # decouple the tuples in the rows
        for i, value in enumerate(dicts):
            dicts[i] = [item for sublist in value for item in sublist]

        # Fill the rows with empty values if needed
        for i, value in enumerate(dicts):
            if len(value) < len(headers):
                dicts[i] += ["", ""] * (len(headers) - len(value))

        rows = dicts

    if table_bet_listed:
        headers = ["user", "bet", "fluxbux"]
        rows = [
            [user, bet, value]
            for user, bets in dictionary.items()
            for bet, value in bets.items()
        ]
    return (
        "```\n"
        + tabulate(rows, headers=headers, tablefmt="outline", numalign="right")
        + "\n```"
    )


async def print_return(statement: str) -> str:
    print(statement)
    return statement


def check_operator_roles() -> Callable:
    async def inner(ctx: discord.ApplicationContext):
        if OPERATOR_ROLE == [None]:
            return True
        if ctx.user.id == int(OPERATOR_ID):
            return True
        if not any(role.name.lower() in OPERATOR_ROLE for role in ctx.user.roles):
            await ctx.defer(ephemeral=True)
            await ctx.respond(
                f"You don't have permission, list of roles is {OPERATOR_ROLE}",
                ephemeral=True,
                delete_after=10,
            )
            return False
        return True

    return inner


class Jsonfy:
    def __init__(self, game):
        self.game = game

    @staticmethod
    async def process_json_queue(json_queue, PROCESS_WAIT_TIME, EMPTY_WAIT_TIME):
        while True:
            try:
                # If the queue is empty, sleep for a short time before checking again
                if json_queue.empty():
                    await asyncio.sleep(EMPTY_WAIT_TIME)
                    continue
                to_json = await json_queue.get()

                formatted_date = datetime.now().strftime("%Y-%m-%d")
                Path("backup").mkdir(exist_ok=True)

                try:
                    async with aiofiles.open(
                        "database.json", "w", encoding="utf-8"
                    ) as f:
                        await f.write(
                            json.dumps(await to_json.game.to_json(), indent=4)
                        )
                except Exception:
                    await asyncio.sleep(PROCESS_WAIT_TIME)
                    raise

                # Save a backup, this is not ran if the first save fails
                async with aiofiles.open(
                    f"backup/database_{formatted_date}.json", "w", encoding="utf-8"
                ) as f:
                    await f.write(json.dumps(await to_json.game.to_json(), indent=4))

                await asyncio.sleep(PROCESS_WAIT_TIME)
            except Exception:
                traceback.print_exc()


class Game:
    def __init__(self, users=None, user_map=None, weeks=None):
        self.users = (
            users if users is not None else {}
        )  # Dictionary to store users and their points
        self.user_map = (
            user_map if user_map is not None else {}
        )  # Dictionary to store users and their points
        self.weeks = (
            weeks if weeks is not None else {}
        )  # Dictionary to store weeks and bets
        self.current_week = str(date.today().isocalendar().week)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        return cls(**data)

    async def to_json(self):
        return {
            "users": self.users,
            "user_map": self.user_map,
            "weeks": self.weeks,
        }

    async def setup_week(self, week):
        if week not in self.weeks:
            self.weeks[week] = {}
        if "options" not in self.weeks[week]:
            self.weeks[week]["options"] = []
        if "result" not in self.weeks[week]:
            self.weeks[week]["result"] = {}
        if "betting_pool" not in self.weeks[week]:
            self.weeks[week]["betting_pool"] = {}
        if "bets" not in self.weeks[week]:
            self.weeks[week]["bets"] = {}
        if "claimed" not in self.weeks[week]:
            self.weeks[week]["claimed"] = {}

    async def add_user(self, name: str):
        if name not in self.users:
            self.users[name] = 0

    async def link(self, user: str, discord_user: discord.User):
        self.user_map[user] = discord_user.id

    async def set_options(self, week: str, options: list, reset: str):
        if reset == "full":
            self.weeks[week]["options"] = []
            self.weeks[week]["betting_pool"] = {}
            self.weeks[week]["bets"] = {}
            self.weeks[week]["result"] = {}
        if reset == "options":
            self.weeks[week]["options"] = []
        self.weeks[week]["options"] += options
        listed_users = "\n".join("- " + user for user in self.weeks[week]["options"])
        return await print_return(f"Set week {week} to:\n{listed_users}")

    async def give_points(self, user, points, week, button=False):
        await self.add_user(user)
        if not button:
            self.users[user] += points
            return await print_return(
                f"Gave {points} fluxbux to {user}, they now have {self.users[user]} fluxbux"
            )
        if button:
            if not self.weeks.get(week).get("claimed").get(user, False):
                self.weeks[week]["claimed"][user] = True
                self.users[user] += points
                return True
            return False

    async def transfer_points(self, from_user, to_user, points, week):
        await self.add_user(from_user)
        await self.add_user(to_user)
        if (await self.spent_points(week, from_user) + points) > self.users.get(
            from_user, 0
        ):
            return f"{from_user} does not have enough fluxbux to transfer\nTransfering and running the bet might net you negative fluxbux."
        self.users[from_user] -= points
        self.users[to_user] += points
        return f"Transferred {points} fluxbux. From {from_user}({self.users[from_user]}) to {to_user}({self.users[to_user]})."

    async def spent_points(self, week, user: str):
        try:
            total_usage = sum(self.weeks[week].get("bets").get(user).values())
        except Exception:
            total_usage = 0
        return total_usage

    async def update_pool(self, week: int):
        betting_pool = {}
        for user, bets in self.weeks[week]["bets"].items():
            for option, value in bets.items():
                if option in betting_pool:
                    betting_pool[option] += value
                else:
                    betting_pool[option] = value
        self.weeks[week]["betting_pool"] = betting_pool

    async def remove_bet(self, week: str, user: str, bet_on: str):
        try:
            del self.weeks[week]["bets"][user][bet_on]
            await self.update_pool(week)
            return f"Removed your bet on {bet_on}"
        except Exception:
            return f"Failed to remove bet on {bet_on}"

    async def place_bet(self, week: str, user: str, bet_on: str, points: int):
        try:
            await self.add_user(user)
            # Check if this week has already finished
            if self.weeks.get(week).get("result") != {}:
                return f"Week {week} has already been ran, you bet on {self.weeks.get(week).get('bets').get(user).get('bet_on')}"
            if points <= 0:
                return "You can't bet less than 0 points"
            # Check if the user has enough points to bet
            if (await self.spent_points(week, user) + points) > self.users.get(user):
                return (
                    f"Insufficient points, you've spent {await self.spent_points(week, user)} points on bets, "
                    f"with a bet of {points} you've gone over your {self.users.get(user)} points"
                )
            # Check if bet_on is an option
            if bet_on not in self.weeks.get(week).get("options", ""):
                return f"{bet_on} is not a valid user to bet on"
            if user in self.weeks.get(week).get("bets"):
                bets = len(set(self.weeks.get(week).get("bets").get(user).keys()))
                options = len(set(self.weeks.get(week).get("options")))
                if options % 2 == 1:
                    options += 1
                if bets >= (options / 2):
                    return f"{user} has made too many bets"

            # Add your user bet if it doesn't exist
            if user not in self.weeks.get(week).get("bets"):
                self.weeks[week]["bets"][user] = {}
            if bet_on not in self.weeks.get(week).get("bets").get(user):
                self.weeks[week]["bets"][user][bet_on] = 0

            # Update bet
            self.weeks[week]["bets"][user][bet_on] = points

            # Update betting pool
            await self.update_pool(week)

            ratio = await self.get_payout_ratio(week=week)
            total_bets = sum(self.weeks.get(week).get("bets").get(user).values())
            percentage = round((total_bets / self.users[user]) * 100, 2)
            return_string = f"**{user}** bet **{points}** fluxbux on **{bet_on}** for a **{ratio}** payout ratio on week {week}.\nYour percentage so far is **{percentage}%** of your fluxbux. The threshold is **10%**."
            return return_string
        except Exception as e:
            traceback.print_exc()
            return e

    async def update_points(self, week: str, roll: str):
        try:
            if week not in self.weeks:
                return await print_return("No game set up for this week")
            betting_pool = sum(
                self.weeks.get(week, {}).get("betting_pool", {}).values()
            )
            winner_pool = self.weeks.get(week).get("betting_pool").get(roll)
            if betting_pool == 0:
                return f"No bets have been made for week {week}"
            if roll not in self.weeks.get(week).get("betting_pool"):
                self.weeks[week]["betting_pool"][roll] = 0
            if "house" not in self.users:
                self.users["house"] = 0
            total_house_comission = 0
            total_house_loss = 0
            total_house_gain = 0
            tax_pool = 0
            taxed = []
            incorrect_bets = 0
            correct_bets = 0
            counter = 0
            outcomes = {}
            for user in self.users:
                if user == "house":
                    continue
                if user not in self.weeks.get(week).get("bets"):
                    tax = round(self.users[user] * 0.3)
                    tax_pool += tax
                    self.users[user] -= tax
                    taxed.append(user)
                    if user == "rickywl":
                        print(tax)
                    outcomes[counter] = {
                        "user": user,
                        "outcome": "taxed",
                        "balance": tax,
                    }
                counter += 1

            for user, bets in self.weeks.get(week).get("bets").items():
                total_bets = sum(bets.values())
                threshhold = 0.1 * self.users[user]
                if total_bets <= threshhold:
                    difference = round(threshhold - total_bets)
                    tax = difference
                    tax_pool += tax
                    self.users[user] -= tax
                    taxed.append(user)
                    outcomes[counter] = {
                        "user": user,
                        "outcome": "taxed",
                        "balance": tax,
                    }
                    counter += 1

                for bet_on, points in bets.items():
                    if bet_on == roll:
                        ratio = await self.get_payout_ratio(week=week)
                        payout = round(points * ratio)
                        house_com = round(payout * 0.05)
                        payout -= house_com  # house comission
                        total_house_comission += house_com
                        total_house_loss += payout
                        self.users[user] += payout
                        correct_bets += 1
                        outcomes[counter] = {
                            "user": user,
                            "outcome": "won",
                            "balance": payout,
                        }
                    elif bet_on != roll:
                        total_house_gain += points
                        self.users[user] -= points
                        incorrect_bets += 1
                        outcomes[counter] = {
                            "user": user,
                            "outcome": "lost",
                            "balance": points,
                        }
                    counter += 1

            if taxed != []:
                bets = list(self.weeks.get(week).get("bets").keys())
                # filter out taxed users
                bets = [user for user in bets if user not in taxed]
                cut = round(tax_pool / len(bets))
                for user in bets:
                    self.users[user] += cut
                    outcomes[counter] = {
                        "user": user,
                        "outcome": "tax return",
                        "balance": cut,
                    }
                    counter += 1

            self.users["house"] += total_house_gain - total_house_loss

            winning_string = ""
            losing_string = ""
            taxed_string = ""
            tax_return_string = ""
            for user, data in outcomes.items():
                if data["outcome"] == "won":
                    winning_string += f"- **{data['user']}** {data['outcome']} **{data['balance']}** fluxbux\n"
                elif data["outcome"] == "lost":
                    losing_string += f"- **{data['user']}** {data['outcome']} **{data['balance']}** fluxbux\n"
                elif data["outcome"] == "taxed":
                    taxed_string += f"- **{data['user']}** {data['outcome']} **{data['balance']}** fluxbux\n"
                elif data["outcome"] == "tax return":
                    tax_return_string += f"- **{data['user']}** {data['outcome']} **{data['balance']}** fluxbux\n"

            winner_id = self.user_map.get(roll.lower(), roll)
            return_string = f"The winner is <@{winner_id}>\n**Gain:**\n{winning_string}**Loss**\n{losing_string}**Taxed:**\n{taxed_string}**Tax return:**\n{tax_return_string}"
            self.weeks[week]["result"] = {
                ":tada: Winner": roll,
                ":white_check_mark: Correct bets": correct_bets,
                "<:redCross:1126317725497692221> Incorrect bets": incorrect_bets,
                ":moneybag: Total betting pool": betting_pool,
                ":moneybag: Winning pool": winner_pool,
                ":moneybag: Total payouts": total_house_loss,
                ":moneybag: Taxes": tax_pool,
                ":moneybag: Taxed players": len(taxed),
                ":house: Total house comission on payouts": total_house_comission,
                ":house: Total fluxbux to house from lost bets": total_house_gain,
                ":house: Total fluxbux gone to the house": total_house_gain
                - total_house_loss,
            }
            return await print_return(f"||{return_string}||")
        except Exception as e:
            traceback.print_exc()
            return e

    async def get_payout_ratio(self, week: str) -> float:
        winning_probability = 1 / len(self.weeks.get(week).get("options"))
        ratio = (1 - winning_probability) / winning_probability
        ratio = round(ratio, 2)
        return ratio

    async def print_status(self, week: str) -> str:
        currency: str = await string_dict(
            self.users, table_listed=True, sort=True, num_columns=2
        )
        betting_pool: str = await string_dict(
            self.weeks.get(week, {}).get("betting_pool", {}),
            table_listed=True,
            sort=True,
            num_columns=2,
        )
        bets: str = await string_dict(
            self.weeks.get(week, {}).get("bets", {}), table_bet_listed=True
        )
        return f":coin: Current fluxbux listing\n{currency}\n:moneybag: Betting pool\n{betting_pool}\n:bar_chart: Bets for week {week}\n{bets}"

    async def print_roll(self, week: str) -> str:
        if week not in self.weeks:
            return f"No spin for week {week}"
        if self.weeks[week]["result"] == {}:
            return f"No spin for week {week}"
        return f"The spin for week {week} is:\n{await string_dict(self.weeks[week]['result'], listed=True)}"

    async def print_user_balance(self, user: str, week: str) -> str:
        if user not in self.users:
            return f"{user} is not a user"
        points = self.users[user]
        user_bets = self.weeks.get(week).get("bets").get(user)
        total_bets = sum(user_bets.values()) if user_bets else 0
        percentage = round((total_bets / self.users[user]) * 100, 2)
        bets = ""
        if user in self.weeks.get(week).get("bets"):
            for bet, bet_points in list(self.weeks.get(week).get("bets").get(user).items()):
                bets += f"- **{bet}**: **{bet_points}**\n"
        return f"You have **{points}** fluxbux and have bet **{percentage}%** of your fluxbux.\n{bets}"


class Commands(discord.Cog, name="Commands"):
    def __init__(self, bot, json_queue):
        self.game: Game = None
        self.bot: discord.Bot = bot
        self.json_queue = json_queue
        self.current_week = str(date.today().isocalendar().week)

    @discord.Cog.listener()
    async def on_ready(self):
        try:
            with open("database.json", "r", encoding="utf-8") as f:
                json_data = json.dumps(json.load(f))
                self.game: Game = Game.from_json(json_data)
                print("Loaded game")
            assert isinstance(self.game, Game)
        except Exception:
            self.game: Game = Game()
            print("Started a new game")

        # setup giveaway views
        view = discord.ui.View(timeout=None)
        for week in self.game.weeks:
            view.add_item(PointButton(self.game, week))
        self.bot.add_view(view)

        print("Starting update loop")
        while True:
            self.current_week = str(date.today().isocalendar().week)
            await self.game.setup_week(self.current_week)
            await self.json_queue.put(Jsonfy(self.game))
            await asyncio.sleep(15)

    async def bet_on_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.weeks[self.current_week]["options"]
        return [user for user in users if user.startswith(ctx.value.lower())][:25]

    async def options_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.users.keys()
        return [user for user in users if user.startswith(ctx.value.lower())][:25]

    async def player_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        users = self.game.users.keys()
        return [user for user in users if user.startswith(ctx.value.lower())][:25]

    async def week_autocompleter(self, ctx: discord.AutocompleteContext):
        if self.game is None:
            await ctx.interaction.response.defer()
            return []
        weeks = self.game.weeks.keys()
        return [week for week in weeks if week.startswith(ctx.value.lower())][:25]

    @discord.slash_command(
        name="set",
        description="Start a betting round",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="users",
        description="Set the users to be able to bet on",
        required=True,
    )
    @discord.option(
        name="reset",
        description="Reset bets",
        choices=["full", "options"],
        required=False,
        default=None,
    )
    @discord.guild_only()
    async def set(self, ctx: discord.ApplicationContext, users: str, reset: str):
        await ctx.defer()
        users = [option.strip() for option in users.split(sep=",")]
        response = await self.game.set_options(self.current_week, users, reset)
        await ctx.respond(response)

    @discord.slash_command(
        name="give",
        description="Give fluxbux",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="user",
        description="Which user to give fluxbux to",
        required=True,
        autocomplete=options_autocompleter,
    )
    @discord.option(
        name="fluxbux", description="How many fluxbux to give", required=True
    )
    @discord.guild_only()
    async def give(
        self, ctx: discord.ApplicationContext, user: discord.User, fluxbux: int
    ):
        await ctx.defer()
        response = await self.game.give_points(user.name, fluxbux, self.current_week)
        await ctx.respond(response)

    @discord.slash_command(
        name="status",
        description="Get fluxbux and the bets for the current week",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="week",
        description="Which week to look up the bets for",
        required=False,
        autocomplete=week_autocompleter,
    )
    @discord.guild_only()
    async def status(self, ctx: discord.ApplicationContext, week: str):
        await ctx.defer()
        if week is None:
            week = self.current_week
        response = await self.game.print_status(week)
        await ctx.respond(response)

    @discord.slash_command(
        name="balance",
        description="Get user balance",
        guild_ids=GUILDS,
    )
    @discord.guild_only()
    async def balance(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        response = await self.game.print_user_balance(ctx.user.name, self.current_week)
        await ctx.respond(response)

    @discord.slash_command(
        name="results",
        description="Get results for a week",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="week",
        description="Which week to look up",
        required=False,
        autocomplete=week_autocompleter,
    )
    @discord.guild_only()
    async def results(self, ctx: discord.ApplicationContext, week: str):
        await ctx.defer()
        if week is None:
            week = self.current_week
        response = await self.game.print_roll(week)
        await ctx.respond(response)

    @discord.slash_command(
        name="bet",
        description="Bet on a person",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="user",
        description="Which user to bet on",
        required=True,
        autocomplete=bet_on_autocompleter,
    )
    @discord.option(
        name="fluxbux",
        description="bux <= 100 = ratio 2, 101 <= bux <= 300 = ratio 1.5, bux > 300 = ratio 1",
        required=True,
    )
    @discord.guild_only()
    async def bet(
        self,
        ctx: discord.ApplicationContext,
        user: str,
        fluxbux: int,
    ):
        await ctx.defer()
        response = await self.game.place_bet(
            self.current_week, ctx.user.name, user, fluxbux
        )
        await ctx.respond(response)

    @discord.slash_command(
        name="remove_bet",
        description="Remove a bet you made",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="user",
        description="Which user remove your bet for",
        required=True,
        autocomplete=bet_on_autocompleter,
    )
    @discord.guild_only()
    async def remove_bet(
        self,
        ctx: discord.ApplicationContext,
        user: str,
    ):
        await ctx.defer(ephemeral=True)
        response = await self.game.remove_bet(self.current_week, ctx.user.name, user)
        await ctx.respond(response)

    @discord.slash_command(
        name="payout",
        description="Payout based on who won",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="winner",
        description="Who won the game",
        required=True,
        autocomplete=bet_on_autocompleter,
    )
    @discord.guild_only()
    async def payout(self, ctx: discord.ApplicationContext, winner: str):
        await ctx.defer()
        response = await self.game.update_points(self.current_week, winner)
        await ctx.respond(response)

    @discord.slash_command(
        name="giveaway",
        description="Make a message which gives away fluxbux for 4 hours",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="week",
        description="Which week to give the fluxbux away as",
        required=False,
        autocomplete=week_autocompleter,
    )
    @discord.guild_only()
    async def giveaway(self, ctx: discord.ApplicationContext, week):
        await ctx.defer()
        if week is None:
            week = self.current_week
        if "claimed" not in self.game.weeks.get(week):
            self.game.weeks[week]["claimed"] = {}
        view = discord.ui.View(timeout=None)
        view.add_item(PointButton(self.game, week))
        await ctx.respond(
            f"Click the button to get 100 fluxbux for week {week}", view=view
        )

    # command to transfer fluxbux from the user who runs the command to another user
    @discord.slash_command(
        name="transfer",
        description="Transfer your fluxbux to another user",
        guild_ids=GUILDS,
    )
    @discord.option(
        name="user",
        description="Which user to transfer to",
        required=True,
        autocomplete=player_autocompleter,
    )
    @discord.option(
        name="fluxbux",
        description="How many fluxbux to transfer",
        required=True,
    )
    @discord.guild_only()
    async def transfer(
        self,
        ctx: discord.ApplicationContext,
        user: str,
        fluxbux: int,
    ):
        await ctx.defer()
        response = await self.game.transfer_points(
            ctx.user.name, user, fluxbux, self.current_week
        )
        await ctx.respond(response)

    @discord.slash_command(
        name="link",
        description="Link a user to a discord user",
        guild_ids=GUILDS,
        checks=[check_operator_roles()],
    )
    @discord.option(
        name="user",
        description="nickname to use",
        required=True,
    )
    @discord.option(
        name="discord_user",
        description="discord user to use",
        required=True,
    )
    async def link(
        self, ctx: discord.ApplicationContext, user: str, discord_user: discord.User
    ):
        await ctx.defer()
        await self.game.link(user, discord_user)
        await ctx.respond(f"Linked {user} and {discord_user.name}")

    # make a help command
    @discord.slash_command(
        name="help",
        description="Get a list of commands",
        guild_ids=GUILDS,
    )
    @discord.guild_only()
    @discord.option(
        name="submenu",
        description="Which submenu to show",
        choices=["commands", "betting", "payout"],
        required=True,
    )
    async def help(self, ctx: discord.ApplicationContext, submenu: str):
        await ctx.defer(ephemeral=True)

        if submenu == "commands":
            embed = discord.Embed(
                title="Fluxbux Commands",
                description="Commands for Fluxbux",
                color=discord.Color.blurple(),
            )
            embed.add_field(
                name="bet",
                value="Bet on someone",
                inline=False,
            )
            embed.add_field(
                name="remove_bet",
                value="Remove a bet on someone",
                inline=False,
            )
            embed.add_field(
                name="balance",
                value="Get your balance",
                inline=False,
            )
            embed.add_field(
                name="transfer",
                value="Transfer fluxbux to another user",
                inline=False,
            )
            embed.add_field(
                name="status",
                value="Get the status of the current week or given week",
                inline=False,
            )
            embed.add_field(
                name="results",
                value="Get the results of the current week or given week",
                inline=False,
            )
            embed.add_field(
                name="help",
                value="Get a list of commands, this command",
                inline=False,
            )
            # add divider for admin commands
            embed.add_field(
                name="================",
                value="",
                inline=False,
            )
            embed.add_field(
                name="set",
                value="Set the current week",
                inline=False,
            )
            embed.add_field(
                name="giveaway",
                value="Make a message which gives away fluxbux for 24 hours",
                inline=False,
            )
            embed.add_field(
                name="payout",
                value="Payout based on who won",
                inline=False,
            )
            embed.add_field(
                name="give",
                value="Give fluxbux to someone",
                inline=False,
            )
            embed.add_field(
                name="link",
                value="Link a user to a discord user",
                inline=False,
            )
        if submenu == "betting":
            embed = discord.Embed(
                title="Bet Command",
                description="Explanation for how betting works",
                color=discord.Color.blurple(),
            )
            embed.add_field(
                name="bet",
                value=(
                    "When you bet on someone, it gets added to a list of bets for that week.\n"
                    "You can't bet more fluxbux than you own at any time.\n"
                    "You can bet on multiple people at a time, but not on the same person twice.\n"
                    "You need to bet at least 10% of your fluxbux to not get taxed.\n"
                    "If you don't bet you'll get taxed 30% of your fluxbux."
                ),
                inline=False,
            )
        if submenu == "payout":
            embed = discord.Embed(
                title="Payout Command",
                description="Explanation for how payout works",
                color=discord.Color.blurple(),
            )
            embed.add_field(
                name="payout",
                value=(
                    "The winner of the week is the one who's spun on the weekly wheel\n"
                    "The commands runs all the bets for the week\n"
                    "The payout is based on the ratio of the week which is based on the amount of options\n"
                    "Any user who hasn't bet yet gets taxed 30% of their fluxbux\n"
                    "Any user who hasn't bet at least 10% of their fluxbux gets taxed up to 10% taking their current bets into account"
                ),
                inline=False,
            )

        await ctx.respond(embed=embed)


class PointButton(discord.ui.Button):
    def __init__(self, game, week):
        super().__init__(
            label="Get Fluxbux",
            style=discord.ButtonStyle.primary,
            custom_id=week,
        )
        self.game = game

    async def callback(self, interaction: discord.Interaction):
        user: discord.User = interaction.user
        game: Game = self.game
        week = str(self.custom_id)
        time_diff = datetime.now(timezone.utc) - interaction.message.created_at
        duration = timedelta(hours=24)

        if time_diff > duration:
            await interaction.response.send_message(
                "It's been more than 24 hours, this is now invalid", ephemeral=True
            )
            return

        gave_points = await game.give_points(
            user=user.name, points=100, week=week, button=True
        )
        if gave_points:
            await interaction.response.send_message(
                f"You got 100 fluxbux for week {week}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"You've already gotten fluxbux for week {week}", ephemeral=True
            )


activity = discord.Activity(
    type=discord.ActivityType.playing, name="Let the fluxbux rain"
)
bot = discord.Bot(intents=discord.Intents.all(), command_prefix="!", activity=activity)


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    if isinstance(error, discord.CheckFailure):
        pass
    else:
        raise error


async def main():
    json_queue = asyncio.Queue()
    asyncio.ensure_future(Jsonfy.process_json_queue(json_queue, 5, 1))
    bot.add_cog(Commands(bot, json_queue))
    await bot.start(os.getenv("DISCORD_TOKEN"))


def init():
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        print("Caught keyboard interrupt")
    except Exception as e:
        traceback.print_exc()
        print(str(e))
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(init())
