Attribute VB_Name = "工作表14"
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
        Get_CFQ Range("B1"), "CFQ"
    Else
        Get_CFQ Range("G1"), "CFQ"
    End If
    Range("B1").Select

End Sub
