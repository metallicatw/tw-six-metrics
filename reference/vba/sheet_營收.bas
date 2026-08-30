Attribute VB_Name = "工作表5"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 14, 1, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    If Range("O1") = "" Then
        Get_REV Range("J1"), "營收"
    Else
        Get_REV Range("O1"), "營收"
    End If
    Range("J1").Select

End Sub
