from airtest.core.api import *
import resource.function.city_guide as guide
import resource.function.base_action as base
import json


def start_battle():
    # touch(Template(filename="resource/template/guide/battle_ready.png", resolution=(1280, 720)))
    loc = base.find_text_include_ocr(text="前往作战")
    if loc:
        touch(loc)
    else:
        return False

    loc = exists(Template(filename="resource/template/guide/cancel.png", resolution=(1280, 720)))
    if loc:
        touch(loc)
        return False
    flag = True
    while flag:
        loc = exists(Template(filename="resource/template/guide/battle_check.png", resolution=(1280, 720)))
        if loc:
            touch((1200, 380))
            flag = False
    return True


def end_battle():
    flag = True
    while flag:
        loc = exists(
            Template(filename="resource/template/guide/quit_battle.png", resolution=(1280, 720), threshold=0.8))
        if loc:
            sleep(5)
            touch(loc)
            flag = False
        sleep(5)


def expel_battle_loop(times=-1):
    while times != 0:
        if start_battle():
            sleep(20)
            end_battle()
        else:
            return False
        times -= 1


def reward_battle_loop(times=-1):
    while times != 0:
        if exists(Template(filename="resource/template/guide/reward_ui.png", resolution=(1280, 720))):
            return True
        if start_battle():
            sleep(20)
            end_battle()
        else:
            return False
        times -= 1
    return True


def changedifficulty(type=0):
    loc = exists(
        Template(filename="resource/template/guide/difficulty.png", resolution=(1280, 720), threshold=0.8))
    if loc:
        touch(loc)

    matchlist = {1: [275, 400], 2: [420, 400], 3: [560, 400], 4: [705, 400], 5: [850, 400], 6: [995, 400]}
    touch(matchlist[type])

    loc = exists(
        Template(filename="resource/template/action/confirm.png", resolution=(1280, 720), threshold=0.8))
    if loc:
        touch(loc)


def chooseenemy(enemy=0):
    if enemy == 0:
        print("无参数运行")
        return False
    matchlist = {1: [620, 660], 2: [890, 660], 3: [1140, 660]}
    touch(matchlist[enemy])
    return True


def test(times=-1, enemy=0, difficult=0):
    guide.enter_city()
    guide.enter_battle()
    sleep(2)
    while True:
        guide.choose(0)
        sleep(1)
        chooseenemy(enemy=enemy)
        if ispurple():
            break
        guide.back()
        sleep(0.5)
    sleep(1)
    changedifficulty(type=difficult)
    expel_battle_loop(times=times)

    guide.backmain()


def battle_type(mission_type=None, aim_city=None, loc_city=None):
    # 这里启动界面应该是城市界面,
    if not mission_type:
        print("空参数")
        return False
    guide.enter_city()
    if not aim_city:
        print("无目标城市，选择本地执行")
    if not aim_city:
        print("未知城市，识别一下")
        loc_city = guide.searchcity()
    match mission_type[0]:
        case 1:
            #   这里是打铁案局的驱逐任务，需要参数是敌人类型（1，2，3），敌人等级（1，2，3，4，5，6），战斗次数（-1-inf）
            guide.enter_battle(cityname=loc_city)
            sleep(2)
            while True:
                guide.choose(0)
                sleep(1)
                chooseenemy(enemy=mission_type[1][0])
                if ispurple():
                    break
                guide.back()
                sleep(0.5)
            sleep(1)
            changedifficulty(type=mission_type[1][1])
            expel_battle_loop(times=mission_type[1][2])
        case 2:
            #   这里是铁案局的悬赏任务，需要参数是战斗次数（-1-inf）我感觉用不上，基本都是打完吧
            guide.enter_battle(cityname=loc_city)
            sleep(2)
            guide.choose(1)
            sleep(1)
            reward_battle_loop(mission_type[1][0])
        case 3:
            #   这里是其他地方的作战任务，需要参数是敌人类型（1-10），战斗次数（-1-inf）
            pass


def ispurple():
    print("这里开始匹配箱子")
    touch((920, 460))
    loc = exists(Template(filename="resource/template/guide/purple_box.png", resolution=(1280, 720), threshold=0.9,
                          record_pos=(555, 220)))
    print(loc)
    if loc:
        touch((470, 660))
        return True
    touch((470, 660))
    return False


def main_city_battle():
    pass
    # todo 这里没想好怎么区分铁案局作战，铁案局悬赏，作战任务这三个的区分，理论到时候还要有个打紫树和白树的，


# todo 研究一下怎么识别紫树和白树
def 识别白树():
    # Load a pretrained YOLOv8n model
    model = YOLO(r'C:\Users\356\Desktop\项目\py\雷索大怪识别\yolo\runs\detect\train_v84\weights\best.pt')

    # Create a random torch tensor of BCHW shape (1, 3, 640, 640) with values in range [0, 1] and type float32

    model.predict(fr"C:\Users\356\Documents\MuMu共享文件夹\Screenshots\MuMu12-20240624-141439.png", imgsz=640,
                  save=True, device=0)
