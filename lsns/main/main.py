import json
from concurrent.futures import ThreadPoolExecutor

import resource.function.battle_action as battle
import resource.function.core as core
import resource.function.game_action as game
import resource.function.base_action as base
import resource.function.trade_action as trade
import resource.function.city_guide as guide
import resource.function.count_price as count
import resource.function.travel_action as travel


def usertest():
    init_flag = False

    executor = ThreadPoolExecutor(max_workers=1)
    while True:
        print("\033c", end="")
        print("选择操作:")
        print("1：启动游戏")
        print("2：关闭游戏")
        print("3：清理日常")
        print("4：循环作战")
        print("5：自动跑商（默认疲劳跑到500停，不会用书")
        print("6：计算当前跑商方案")
        print("7：更新并显示用户数据")
        print("8：测试部分（不用")

        print("")

        choose = int(input())

        if (not init_flag):
            print("正在链接")
            game.init()
            init_flag = True
            print("链接结束")
        match choose:
            case 1:
                # 这里需要检查是否有执行具体操控的任务，如果有，不进行任务
                print("\033c", end="")
                executor.submit(game.startupapp)
                print("添加任务成功")
            case 2:
                # 这里需要检查是否有执行具体操控的任务，如果有，报错
                print("\033c", end="")
                mission_id = executor.submit(game.closeapp)
                print("添加任务成功")
            case 3:
                # 这里需要检查是否有执行具体操控的任务
                print("\033c", end="")
                executor.submit(lambda p: core.daily_work(*p), [None, 3])
                print("添加任务成功")
            case 4:
                # 这里需要检查是否有执行具体操控的任务
                print("\033c", end="")
                executor.submit(battle.expel_battle_loop)
                print("添加任务成功")
            case 5:
                # 这里需要检查是否有执行具体操控的任务
                print("\033c", end="")
                fatigue_limit = int(input("疲劳跑到多少,输入0就是默认到500"))
                book = int(input("book_num="))
                executor.submit(lambda p: core.business_traffic(*p),
                                [None, book, fatigue_limit if fatigue_limit != 0 else 500])
                print("添加任务成功")
            case 6:
                print("\033c", end="")
                book = int(input("book_num="))
                mission = executor.submit(lambda p: core.monitor_data(*p), [book])
                mission.result()
                print("添加任务成功")
            case 7:
                # 这里需要检查是否有执行具体操控的任务
                executor.submit(lambda p: core.show_user_inf(*p), [])
                print("添加任务成功")
            case 8:

                game.rotate_shop_product()


if __name__ == "__main__":
    while True:
        usertest()
        # try:
        #     usertest()
        # except:
        #     print("\n有点问题，重新启动一下\n")

if __name__ == "main":
    while True:
        try:
            usertest()
        except:
            print("\n有点问题，重新启动一下\n")
