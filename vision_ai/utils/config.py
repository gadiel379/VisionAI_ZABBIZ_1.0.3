import yaml

class Config:

    def __init__(self):

        with open("config/config.yaml") as f:
            self.data = yaml.safe_load(f)

    def get(self, section, key):
        return self.data[section][key]
