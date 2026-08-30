Attribute VB_Name = "工作表10"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 3, 1, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    If Range("G1") = "" Then
        Get_data_from_MoneyDJ_年財務比率 Range("B1"), "MoneyDJ年財務比率"
    Else
        Get_data_from_MoneyDJ_年財務比率 Range("G1"), "MoneyDJ年財務比率"
    End If
    Range("B1").Select

End Sub
