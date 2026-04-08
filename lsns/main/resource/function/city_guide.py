from airtest.core.api import *
import resource.function.base_action as base


# 这里是从主界面进入城市界面
def enter_port():
    if not is_main():
        backmain()
    while True:
        if loc := base.find_text_include_ocr(text="港区"):
            base.touch(loc)
            base.sleep(1)
            return True

def enter_fight():
    if not is_main():
        backmain()
    while True:
        if loc := base.find_text_include_ocr(text="出击"):
            base.touch(loc)
            base.sleep(1)
            return True

def enter_fight_type(choose = None):
    base_loc = (90,150)
    offset_y = 75
    var = {"主线": 0,"日常":1 ,"远征":2,"演习":3,"竞技":4}
    if type(choose) == str:
        touch((base_loc[0], base_loc[1] + offset_y * var[choose]))
    elif type(choose) == int:
        touch((base_loc[0],base_loc[1]+offset_y*choose))

def is_main():
    return True if exists(Template(filename="resource/template/guide/shop_ui.png", resolution=(1280, 720))) else False


# 用来回到主界面
def backmain():
    """
    回到主界面
    :return:
    """
    flag = True
    while flag:
        loc = exists(Template(filename="resource/template/guide/home.png", resolution=(1280, 720), threshold=0.9))
        if loc:
            touch(loc)
            flag = False
            sleep(1)


def back():
    """
    回退
    :return:
    """
    flag = True
    while flag:
        loc = exists(Template(filename="resource/template/guide/return.png", resolution=(1280, 720), threshold=0.9))
        if loc:
            touch(loc)
            flag = False
            sleep(1)
        sleep(1)

