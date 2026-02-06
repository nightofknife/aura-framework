package autobattle

import (
	"encoding/json"
	"image"
	"time"

	"github.com/MaaXYZ/maa-framework-go/v4"
	"github.com/rs/zerolog/log"
)

type ExecuteParam struct {
	RepeatTimes *int `json:"repeat_times,omitempty"`

	TouchPromptTemplate   *string `json:"touch_prompt_template,omitempty"`
	BattleEndTemplate     *string `json:"battle_end_template,omitempty"`
	SkillPromptTemplate   *string `json:"skill_prompt_template,omitempty"`
	RewardHarvestTemplate *string `json:"reward_harvest_template,omitempty"`
	RewardX1Template      *string `json:"reward_x1_template,omitempty"`
	RewardClaimTemplate   *string `json:"reward_claim_template,omitempty"`
	RestartPromptTemplate *string `json:"restart_prompt_template,omitempty"`
	LeaveTemplate         *string `json:"leave_template,omitempty"`
	RetryTemplate         *string `json:"retry_template,omitempty"`

	ExitModel     *string  `json:"exit_model,omitempty"`
	ExitClassID   *int     `json:"exit_class_id,omitempty"`
	ExitThreshold *float64 `json:"exit_threshold,omitempty"`

	SkillBarROI        []int    `json:"skill_bar_roi,omitempty"`
	SkillSlotCount     *int     `json:"skill_slot_count,omitempty"`
	SkillReadyHSVLow   []int    `json:"skill_ready_hsv_lower,omitempty"`
	SkillReadyHSVHigh  []int    `json:"skill_ready_hsv_upper,omitempty"`
	SkillReadyMinRatio *float64 `json:"skill_ready_min_ratio,omitempty"`

	WMaxSeconds        *float64 `json:"w_max_seconds,omitempty"`
	TouchTimeout       *float64 `json:"touch_timeout,omitempty"`
	BattleEndTimeout   *float64 `json:"battle_end_timeout,omitempty"`
	SettleTimeout      *float64 `json:"settle_timeout,omitempty"`
	Interval           *float64 `json:"interval,omitempty"`
	SkillCheckInterval *float64 `json:"skill_check_interval,omitempty"`
	SkillCastInterval  *float64 `json:"skill_cast_interval,omitempty"`
	ESkillInterval     *float64 `json:"e_interval,omitempty"`
	MatchThreshold     *float64 `json:"match_threshold,omitempty"`
}

type AutoBattleExecuteAction struct{}

func (a *AutoBattleExecuteAction) Run(ctx *maa.Context, arg *maa.CustomActionArg) bool {
	params := ExecuteParam{}
	if arg.CustomActionParam != "" {
		if err := json.Unmarshal([]byte(arg.CustomActionParam), &params); err != nil {
			log.Error().Err(err).Msg("AutoBattleExecuteAction: failed to parse params")
			return false
		}
	}

	// Defaults
	repeatTimes := 1
	if params.RepeatTimes != nil && *params.RepeatTimes > 0 {
		repeatTimes = *params.RepeatTimes
	}
	touchPrompt := valueOr(params.TouchPromptTemplate, "AutoBattleFight/TouchPrompt.png")
	battleEnd := valueOr(params.BattleEndTemplate, "AutoBattleFight/BattleEnd.png")
	skillPrompt := valueOr(params.SkillPromptTemplate, "RealTimeTask/AutoFightCombo.png")
	rewardHarvest := valueOr(params.RewardHarvestTemplate, "AutoBattleFight/RewardHarvest.png")
	rewardX1 := valueOr(params.RewardX1Template, "AutoBattleFight/RewardX1.png")
	rewardClaim := valueOr(params.RewardClaimTemplate, "AutoBattleFight/RewardClaim.png")
	restartPrompt := valueOr(params.RestartPromptTemplate, "AutoBattleFight/RestartPrompt.png")
	leaveTemplate := valueOr(params.LeaveTemplate, "AutoBattleFight/Leave.png")
	retryTemplate := valueOr(params.RetryTemplate, "AutoBattleFight/Retry.png")

	exitModel := valueOr(params.ExitModel, "level_battle.onnx")
	exitClassID := valueOrInt(params.ExitClassID, 0)
	exitThreshold := valueOrFloat(params.ExitThreshold, 0.8)

	skillBar := toRect(params.SkillBarROI, [4]int{400, 600, 500, 120})
	skillSlots := valueOrInt(params.SkillSlotCount, 3)
	hsvLow := toTriple(params.SkillReadyHSVLow, [3]int{20, 120, 150})
	hsvHigh := toTriple(params.SkillReadyHSVHigh, [3]int{40, 255, 255})
	skillMinRatio := valueOrFloat(params.SkillReadyMinRatio, 0.18)

	wMaxSeconds := valueOrFloat(params.WMaxSeconds, 4.0)
	touchTimeout := valueOrFloat(params.TouchTimeout, 8.0)
	battleEndTimeout := valueOrFloat(params.BattleEndTimeout, 120.0)
	settleTimeout := valueOrFloat(params.SettleTimeout, 15.0)
	interval := valueOrFloat(params.Interval, 0.2)
	skillCheckInterval := valueOrFloat(params.SkillCheckInterval, 0.4)
	skillCastInterval := valueOrFloat(params.SkillCastInterval, 0.8)
	eInterval := valueOrFloat(params.ESkillInterval, 1.0)
	matchThreshold := valueOrFloat(params.MatchThreshold, 0.8)

	controller := ctx.GetTasker().GetController()
	if controller == nil {
		log.Error().Msg("AutoBattleExecuteAction: controller is nil")
		return false
	}

	centerX, centerY := getScreenCenter(controller)

	for round := 0; round < repeatTimes; round++ {
		log.Info().
			Int("round", round+1).
			Int("repeat_times", repeatTimes).
			Msg("AutoBattleExecuteAction: round start")
		// Pre-check: wait for "exct" template before starting
		if hit := waitTemplate(ctx, controller, "AutoBattleFight/exct.png", matchThreshold, 60.0, interval); hit == nil {
			log.Warn().Msg("AutoBattleExecuteAction: exct template not found, skip this round")
			continue
		}
		log.Info().Msg("AutoBattleExecuteAction: exct template found")
		time.Sleep(durationSeconds(1.0))
		// Step 0: move forward and wait for touch prompt
		touchFound := false
		controller.PostKeyDown(keycodeW).Wait()
		touchStart := time.Now()
		wReleased := false
		for time.Since(touchStart).Seconds() < touchTimeout {
			img, ok := captureImage(controller)
			if ok {
				if hit := matchTemplate(ctx, img, touchPrompt, matchThreshold, nil); hit != nil {
					touchFound = true
					controller.PostClickKey(keycodeF).Wait()
					log.Info().Msg("AutoBattleExecuteAction: touch prompt found, pressed F")
					break
				}
			}
			if !wReleased && time.Since(touchStart).Seconds() >= wMaxSeconds {
				controller.PostKeyUp(keycodeW).Wait()
				wReleased = true
			}
			time.Sleep(durationSeconds(interval))
		}
		controller.PostKeyUp(keycodeW).Wait()
		if !touchFound {
			log.Warn().Msg("AutoBattleExecuteAction: touch prompt not found, skip battle loop")
			continue
		}

		// Step 1: battle loop (left mouse hold disabled temporarily)
		log.Info().Msg("AutoBattleExecuteAction: battle loop start")
		lastSkillCheck := time.Now()
		lastCast := time.Time{}
		lastE := time.Time{}
		skillIndex := 1
		battleStart := time.Now()
		battleEnded := false
		for time.Since(battleStart).Seconds() < battleEndTimeout {
			img, ok := captureImage(controller)
			if !ok {
				time.Sleep(durationSeconds(interval))
				continue
			}

			if hit := matchTemplate(ctx, img, battleEnd, matchThreshold, nil); hit != nil {
				battleEnded = true
				log.Info().Msg("AutoBattleExecuteAction: battle end detected")
				break
			}

			if time.Since(lastE).Seconds() >= eInterval {
				skillROI := maa.Rect{750, 250, 100, 100}
				if hit := matchTemplate(ctx, img, skillPrompt, matchThreshold, &skillROI); hit != nil {
					controller.PostClickKey(keycodeE).Wait()
					lastE = time.Now()
					log.Info().Msg("AutoBattleExecuteAction: skill prompt detected, pressed E")
				}
			}

			if time.Since(lastSkillCheck).Seconds() >= skillCheckInterval {
				lastSkillCheck = time.Now()
				readyCount := detectReadySlots(ctx, img, skillBar, skillSlots, hsvLow, hsvHigh, skillMinRatio)
				if readyCount > 2 && time.Since(lastCast).Seconds() >= skillCastInterval {
					controller.PostClickKey(int32(keycode1 + (skillIndex - 1))).Wait()
					skillIndex++
					if skillIndex > 4 {
						skillIndex = 1
					}
					lastCast = time.Now()
					log.Info().
						Int("ready_count", readyCount).
						Int("skill_index", skillIndex).
						Msg("AutoBattleExecuteAction: cast skill")
				}
			}
			time.Sleep(durationSeconds(interval))
		}
		// controller.PostTouchUp(0).Wait()
		if !battleEnded {
			time.Sleep(durationSeconds(1.0))
		}

		// Step 2: detect exit by YOLO and align (X axis only)
		log.Info().Msg("AutoBattleExecuteAction: exit search start")
		rewardFound := false
		searchStart := time.Now()
		for time.Since(searchStart).Seconds() < settleTimeout {
			img, ok := captureImage(controller)
			if !ok {
				time.Sleep(durationSeconds(interval))
				continue
			}

			box := detectExitByYolo(ctx, img, exitModel, exitClassID, exitThreshold)
			if box == nil {
				// rotate camera and retry detection
				rotateCameraX(controller, centerX, centerY, 120)
				log.Debug().Msg("AutoBattleExecuteAction: exit not found, rotate camera")
				time.Sleep(durationSeconds(interval))
				continue
			}

			cx, _ := rectCenter(box)
			dx := int32(centerX) - int32(cx)
			if absInt32(dx) > 40 {
				rotateCameraX(controller, centerX, centerY, -dx)
				log.Debug().Int32("dx", dx).Msg("AutoBattleExecuteAction: align exit on X")
				time.Sleep(durationSeconds(interval))
				continue
			}

			// aligned enough, move forward and look for reward prompt
			controller.PostKeyDown(keycodeW).Wait()
			moveStart := time.Now()
			for time.Since(moveStart).Seconds() < settleTimeout {
				img, ok := captureImage(controller)
				if ok {
					if hit := matchTemplate(ctx, img, rewardHarvest, matchThreshold, nil); hit != nil {
						cx, cy := rectCenter(hit)
						controller.PostClick(int32(cx), int32(cy)).Wait()
						rewardFound = true
						log.Info().Msg("AutoBattleExecuteAction: reward harvest detected and clicked")
						break
					}
				}
				time.Sleep(durationSeconds(interval))
			}
			controller.PostKeyUp(keycodeW).Wait()
			break
		}

		// Step 4: reward claim flow
		if rewardFound {
			if hit := waitTemplate(ctx, controller, rewardX1, matchThreshold, settleTimeout, interval); hit != nil {
				cx, cy := rectCenter(hit)
				controller.PostClick(int32(cx), int32(cy)).Wait()
				log.Info().Msg("AutoBattleExecuteAction: reward x1 clicked")
			}
			if hit := waitTemplate(ctx, controller, rewardClaim, matchThreshold, settleTimeout, interval); hit != nil {
				cx, cy := rectCenter(hit)
				controller.PostClick(int32(cx), int32(cy)).Wait()
				log.Info().Msg("AutoBattleExecuteAction: reward claim clicked")
			}
		}

		// Step 5: restart or leave
		if hit := waitTemplate(ctx, controller, restartPrompt, matchThreshold, settleTimeout, interval); hit != nil {
			if round+1 >= repeatTimes {
				if leave := waitTemplate(ctx, controller, leaveTemplate, matchThreshold, settleTimeout, interval); leave != nil {
					cx, cy := rectCenter(leave)
					controller.PostClick(int32(cx), int32(cy)).Wait()
					log.Info().Msg("AutoBattleExecuteAction: leave clicked, end")
					return true
				}
			} else {
				if retry := waitTemplate(ctx, controller, retryTemplate, matchThreshold, settleTimeout, interval); retry != nil {
					cx, cy := rectCenter(retry)
					controller.PostClick(int32(cx), int32(cy)).Wait()
					log.Info().Msg("AutoBattleExecuteAction: retry clicked, next round")
					continue
				}
			}
		}
	}

	return true
}

const (
	keycodeW = 87
	keycodeE = 69
	keycodeF = 70
	keycode1 = 49
)

func durationSeconds(v float64) time.Duration {
	if v <= 0 {
		return 0
	}
	return time.Duration(v * float64(time.Second))
}

func valueOr(ptr *string, def string) string {
	if ptr == nil || *ptr == "" {
		return def
	}
	return *ptr
}

func valueOrInt(ptr *int, def int) int {
	if ptr == nil {
		return def
	}
	return *ptr
}

func valueOrFloat(ptr *float64, def float64) float64 {
	if ptr == nil {
		return def
	}
	return *ptr
}

func toRect(vals []int, def [4]int) maa.Rect {
	if len(vals) == 4 {
		return maa.Rect{vals[0], vals[1], vals[2], vals[3]}
	}
	return maa.Rect{def[0], def[1], def[2], def[3]}
}

func toTriple(vals []int, def [3]int) [3]int {
	if len(vals) == 3 {
		return [3]int{vals[0], vals[1], vals[2]}
	}
	return def
}

func getScreenCenter(controller *maa.Controller) (int32, int32) {
	w, h, err := controller.GetResolution()
	if err != nil || w <= 0 || h <= 0 {
		return 640, 360
	}
	return w / 2, h / 2
}

func captureImage(controller *maa.Controller) (image.Image, bool) {
	if controller == nil {
		return nil, false
	}
	if !controller.PostScreencap().Wait().Success() {
		return nil, false
	}
	img, err := controller.CacheImage()
	if err != nil || img == nil {
		return nil, false
	}
	return img, true
}

func matchTemplate(ctx *maa.Context, img image.Image, template string, threshold float64, roi *maa.Rect) *maa.Rect {
	if template == "" {
		return nil
	}
	param := maa.NodeTemplateMatchParam{
		Template:  []string{template},
		Threshold: []float64{threshold},
		OrderBy:   maa.NodeTemplateMatchOrderByScore,
	}
	if roi != nil {
		param.ROI = maa.NewTargetRect(*roi)
	}
	detail, err := ctx.RunRecognitionDirect(maa.NodeRecognitionTypeTemplateMatch, param, img)
	if err != nil || detail == nil || !detail.Hit || detail.Results == nil || len(detail.Results.Best) == 0 {
		return nil
	}
	res, ok := detail.Results.Best[0].AsTemplateMatch()
	if !ok {
		return nil
	}
	rect := res.Box
	return &rect
}

func detectExitByYolo(ctx *maa.Context, img image.Image, model string, classID int, threshold float64) *maa.Rect {
	param := maa.NodeNeuralNetworkDetectParam{
		Model:    model,
		Expected: []int{classID},
		OrderBy:  maa.NodeNeuralNetworkDetectOrderByScore,
	}
	detail, err := ctx.RunRecognitionDirect(maa.NodeRecognitionTypeNeuralNetworkDetect, param, img)
	if err != nil || detail == nil || !detail.Hit || detail.Results == nil || len(detail.Results.Best) == 0 {
		return nil
	}
	res, ok := detail.Results.Best[0].AsNeuralNetworkDetect()
	if !ok {
		return nil
	}
	if res.Score < threshold {
		return nil
	}
	rect := res.Box
	return &rect
}

func rectCenter(rect *maa.Rect) (int, int) {
	if rect == nil {
		return 0, 0
	}
	return rect.X() + rect.Width()/2, rect.Y() + rect.Height()/2
}

func detectReadySlots(
	ctx *maa.Context,
	img image.Image,
	roi maa.Rect,
	slotCount int,
	hsvLow [3]int,
	hsvHigh [3]int,
	minRatio float64,
) int {
	if slotCount <= 0 || roi.Width() <= 0 || roi.Height() <= 0 {
		return 0
	}
	slotW := roi.Width() / slotCount
	if slotW <= 0 {
		return 0
	}
	ready := 0
	for i := 0; i < slotCount; i++ {
		x := roi.X() + i*slotW
		w := slotW
		if i == slotCount-1 {
			w = roi.Width() - slotW*(slotCount-1)
		}
		slotRect := maa.Rect{x, roi.Y(), w, roi.Height()}
		count := int(float64(slotRect.Width()*slotRect.Height()) * minRatio)
		if count <= 0 {
			count = 1
		}
		param := maa.NodeColorMatchParam{
			ROI:    maa.NewTargetRect(slotRect),
			Method: maa.NodeColorMatchMethodHSV,
			Lower:  [][]int{{hsvLow[0], hsvLow[1], hsvLow[2]}},
			Upper:  [][]int{{hsvHigh[0], hsvHigh[1], hsvHigh[2]}},
			Count:  count,
		}
		detail, err := ctx.RunRecognitionDirect(maa.NodeRecognitionTypeColorMatch, param, img)
		if err == nil && detail != nil && detail.Hit {
			ready++
		}
	}
	return ready
}

func waitTemplate(
	ctx *maa.Context,
	controller *maa.Controller,
	template string,
	threshold float64,
	timeout float64,
	interval float64,
) *maa.Rect {
	if template == "" {
		return nil
	}
	start := time.Now()
	for time.Since(start).Seconds() < timeout {
		img, ok := captureImage(controller)
		if ok {
			if hit := matchTemplate(ctx, img, template, threshold, nil); hit != nil {
				return hit
			}
		}
		time.Sleep(durationSeconds(interval))
	}
	return nil
}

func rotateCameraX(controller *maa.Controller, centerX, centerY int32, dx int32) {
	if controller == nil {
		return
	}
	if dx > 200 {
		dx = 200
	}
	if dx < -200 {
		dx = -200
	}
	if dx == 0 {
		return
	}
	startX := centerX
	startY := centerY
	endX := centerX + dx
	endY := centerY
	controller.PostTouchDown(1, startX, startY, 1).Wait()
	controller.PostTouchMove(1, endX, endY, 1).Wait()
	controller.PostTouchUp(1).Wait()
}

func absInt32(v int32) int32 {
	if v < 0 {
		return -v
	}
	return v
}
