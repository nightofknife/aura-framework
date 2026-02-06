package autobattle

import "github.com/MaaXYZ/maa-framework-go/v4"

var _ maa.CustomActionRunner = &AutoBattleExecuteAction{}

// Register registers custom action for auto battle.
func Register() {
	maa.AgentServerRegisterCustomAction("AutoBattleExecuteAction", &AutoBattleExecuteAction{})
}
