Attribute VB_Name = "工作表8"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 8, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    SName = "股價(週)"
    股號 = Mid(Sheets("EPS預估與估價").Range("A1"), Len(Sheets("EPS預估與估價").Range("A1")) - 5, 4)
    MoneyDJ_TW_PRICE_New SName, 股號, "W"       '111/1/8 改用陣列，加快執行速度
    Range("Z1").Select

End Sub
